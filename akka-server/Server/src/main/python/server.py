import logging
import argparse
import re
import sys
import asyncio
import numpy as np
import torch
import random
import torch.nn as nn
from torchvision import models
import torch.nn.functional as F
from torchvision import datasets, transforms
from pathlib import Path
import json
import os
from torchvision.models.mobilenet import mobilenet_v2
from model_configurations.simple_cnn import CNN
from model_configurations.mnist_model import MNIST
from model_configurations.mimic_model import MIMIC
from model_configurations.chess_model import Chess
from model_configurations.sign_model import Gestures

import syft as sy
from syft.workers import websocket_client
from syft.frameworks.torch.fl import utils


websocket_client.TIMEOUT_INTERVAL = 600
LOG_INTERVAL = 25

logger = logging.getLogger("run_websocket_client")


class LearningMember(object):
    def __init__(self, j):
        self.__dict__ = json.loads(j)

class MockUp():

    def __init__(self, data, targets):
        self.data =data#.astype(np.float32)
        self.targets = targets#.astype('long')

        self.data, self.targets


# Loss function
#@torch.jit.script
#def loss_fn(pred, target):
#    return F.nll_loss(input=pred, target=target.long())


@torch.jit.script
def loss_fn(pred, target):
    return F.cross_entropy(input=pred, target=target.long())

def define_and_get_arguments(args=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        description="Run federated learning using websocket client workers."
    )
    parser.add_argument("--secure_agg", default="False", action="store", help="secure aggregation")
    parser.add_argument("--batch_size", type=int, default=32, help="batch size of the training")
    parser.add_argument(
        "--test_batch_size", type=int, default=128, help="batch size used for the test data"
    )
    parser.add_argument(
        "--training_rounds", type=int, default=40, help="number of federated learning rounds"
    )
    parser.add_argument(
        "--federate_after_n_batches",
        type=int,
        default=1,
        help="number of training steps performed on each remote worker before averaging",
    )
    parser.add_argument("--lr", type=float, default=0.0001, help="learning rate")
    parser.add_argument("--cuda", default = True, action="store_true", help="use cuda")
    parser.add_argument("--seed", type=int, default=1, help="seed used for randomization")
    parser.add_argument("--save_model", action="store_true", help="if set, model will be saved")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="if set, websocket client workers will be started in verbose mode",
    )

    parser.add_argument("--datapath", help="show program version", action="store", default="../data")
    parser.add_argument("--pathToResources", help="where to store", action="store", default="")
    parser.add_argument("--participantsjsonlist", help="show program version", action="store", default="{}")
    parser.add_argument("--epochs", type=int, help="show program version", action="store", default=10)
    parser.add_argument("--model_config", default="vgg")
    parser.add_argument("--model_output", default=5)
    parser.add_argument("--modelpath", default = 'saved_model')
    parser.add_argument("--learningTaskId", default = 'mnist')

    args = parser.parse_args(args=args)
    return args


async def fit_model_on_worker(
    worker: websocket_client.WebsocketClientWorker,
    
    traced_model: torch.jit.ScriptModule,
    batch_size: int,
    curr_round: int,
    max_nr_batches: int,
    lr: float,
    device: str,
    learningTaskId: str
):

    train_config = sy.TrainConfig(
            model=traced_model,
            loss_fn=loss_fn,
            batch_size = batch_size,
            shuffle=True,
            max_nr_batches=max_nr_batches,
            epochs=1,
            optimizer="Adam",
            optimizer_args={"lr": lr, "weight_decay": lr*0.1},
    )
    train_config.send(worker)
    loss = await worker.async_fit(dataset_key=learningTaskId, return_ids=[0], device = device)
    model = train_config.model_ptr.get().obj
    return worker.id, model, loss


async def test(test_worker, traced_model, batch_size, federate_after_n_batches, learning_rate, model_output, device, learningTaskId):
    
    model_config = sy.TrainConfig(
        model=traced_model,
        loss_fn=loss_fn,
        batch_size=batch_size,
        shuffle=True,
        max_nr_batches=federate_after_n_batches,
        epochs=1,
        optimizer="Adam",
        optimizer_args={"lr": learning_rate, "weight_decay": learning_rate*0.1},
    )
    with torch.no_grad():
        model_config.send(test_worker)
        worker_result = test_worker.evaluate(dataset_key=learningTaskId, return_histograms = False, nr_bins = model_output, device = device)
    #return worker_result['nr_correct_predictions'], worker_result['nr_predictions'], worker_result['loss'], worker_result['histogram_target'],  worker_result['histogram_predictions']
    return worker_result['nr_correct_predictions'], worker_result['nr_predictions'], worker_result['loss']

def define_model(model_config, device, modelpath, model_output): 
    model_file = Path(modelpath)
    test_tensor = torch.zeros([1, 3, 224, 224])
    if (model_config == 'mobilenetv2'):
        model = mobilenet_v2(pretrained = True)
        model.classifier[1].out_features = model_output
        model.eval()
        model.to(device)
        transform = transforms.Compose([
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        test_tensor[0] = transform(test_tensor[0])

    if (model_config == 'cnn'):
        model = CNN(3, model_output).to(device)
    
    if (model_config == 'mnist'):
        model = MNIST().to(device)
        test_tensor = torch.zeros([1, 1, 28, 28])
    if (model_config == 'chess'):
        model = Chess().to(device)
        test_tensor = torch.zeros([1, 1, 64, 64])
    if (model_config == 'mimic'):
        model = MIMIC().to(device)
        test_tensor = torch.zeros([1, 48, 19])
    if (model_config == 'gestures'):
        model = Gestures().to(device)
        test_tensor = torch.zeros([1, 1, 28, 28])

    if model_file.is_file():
        model.load_state_dict(torch.load(modelpath))
    return model, test_tensor

def define_participants_lists(participantsjsonlist, **kwargs_websocket):
        
    participants = participantsjsonlist.replace("'","\"")
    participants = json.loads(participants)
    print(participants)

    for_test = random.choices(participants, k = np.int(np.round(len(participants)*0.3)))
    print('Clients picked for test: \n')
    print(for_test)
    worker_instances = []
    worker_instances_test = []
    for participant in participants:
        print("----------------------")
        print(participant['id'])
        print(participant['port'])
        print("----------------------")
        if participant not in for_test:
            worker_instances.append(sy.workers.websocket_client.WebsocketClientWorker(id=participant['id'], port=participant['port'], **kwargs_websocket))
        else:
            worker_instances_test.append(sy.workers.websocket_client.WebsocketClientWorker(id=participant['id'], port=participant['port'], **kwargs_websocket))

    for wcw in worker_instances:
        wcw.clear_objects_remote()

    for wcw in worker_instances_test:
        wcw.clear_objects_remote()
    
    return worker_instances, worker_instances_test

async def main():
    #set up environment
    args = define_and_get_arguments()
    #os.chdir('./akka-server/Server/')
    torch.manual_seed(args.seed)
    print(args)
    hook = sy.TorchHook(torch)

    #define model
    use_cuda = args.cuda and torch.cuda.is_available()
    print(torch.cuda.is_available())
    device = torch.device("cuda" if use_cuda else "cpu")
    model, test_tensor = define_model(args.model_config, device, args.modelpath, int(args.model_output))
    #for p in model.parameters():
    #    p.register_hook(lambda grad: torch.clamp(grad, -6, 6))
    kwargs_websocket = {"hook": hook, "verbose": args.verbose, "host": 'localhost'}
    #define participants
    print(args.participantsjsonlist)

    if args.secure_agg=="True": # while using secure aggregation
        participantsjsonlist = json.loads(args.participantsjsonlist.replace("'","\""))
        interResList = {} #make list of participants' weights
        for participantdata in participantsjsonlist:
            participant = participantdata["id"]
            weightpath = args.pathToResources+"/interRes/"+participant+".pt"
            if os.path.exists(weightpath): # cleanup
                interResList[participant] = torch.load(weightpath)
                os.remove(weightpath)
                p = participant
        os.rmdir(args.pathToResources+"/interRes") # cleanup

        # calculate aggregated weights
        aggregatedWeights = {}
        for weights in interResList[p]:
            aggregatedWeights[weights] = torch.zeros(interResList[p][weights].size())
            for participant in interResList:
                aggregatedWeights[weights] = aggregatedWeights[weights] + interResList[participant][weights] / len(interResList)

        model.load_state_dict(aggregatedWeights) # load model
        traced_model = model

    else: # if no secure aggregation
        worker_instances, worker_instances_test = define_participants_lists(args.participantsjsonlist, **kwargs_websocket)
        traced_model = torch.jit.trace(model,  test_tensor.to(device))
        traced_model.train()
        best_loss = np.Inf
        early_stopping = 25
        learning_rate = args.lr
        for curr_round in range(1, args.epochs + 1):
            logger.info("Training epoch %s/%s", curr_round, args.epochs)
            results = await asyncio.gather(
                *[
                    fit_model_on_worker(

                        worker=worker,
                        traced_model=traced_model,
                        batch_size=args.batch_size,
                        curr_round=curr_round,
                        max_nr_batches=args.federate_after_n_batches,
                        lr=learning_rate,
                        device = device,
                        learningTaskId=args.learningTaskId
                    )
                    for worker in worker_instances
                ]
            )
            models = {}
            models_list =[]
            loss_values = []

            for worker_id, worker_model, worker_loss in results:
                if worker_model is not None:
                    models[worker_id] = worker_model
                    models_list.append(worker_model)
                    loss_values.append(worker_loss)

            traced_model = utils.federated_avg(models)
            # if args.model_config != 'cnn':
            #     print(traced_model.classifier.state_dict())
            # else:
            #     print(traced_model.fc2.weight.data)
            # if curr_round > 0:
            #     learning_rate = learning_rate/ (np.sqrt(curr_round + 1))
            # else:
            #     learning_rate = learning_rate / 2

            correct_predictions = 0
            all_predictions = 0
            traced_model.eval()
            if len(worker_instances_test) > 0 :
                results = await asyncio.gather(
                    *[
                        test(worker_test, traced_model,
                        args.batch_size,
                        args.federate_after_n_batches, learning_rate, int(args.model_output),
                        "cuda" if use_cuda else "cpu", args.learningTaskId)
                        for worker_test in worker_instances_test
                    ]
                )
                test_loss = []
                for curr_correct, total_predictions, loss in results:#, target_hist, predictions_hist in results:
                    correct_predictions += curr_correct
                    all_predictions += total_predictions
                    test_loss.append(loss)
                    # print('Got predictions: \n')
                    # print(predictions_hist)
                    # print('Expected: \n')
                    # print(target_hist)

                mean_loss = np.mean(np.asarray(test_loss))
                print("Currrent accuracy: " + str(correct_predictions/all_predictions))
                print(test_loss)
                print(mean_loss)
                if best_loss > mean_loss:
                    best_loss = mean_loss
                    stop = 0
                    learning_rate = 0.98 * learning_rate
                else:
                    stop += 1
                    learning_rate = 0.9 * learning_rate
                    #learning_rate = learning_rate/ (np.sqrt(curr_round + 1))
                if stop >= early_stopping:
                    print('Warning! Test loss is not improving for 20 iterations or more.')
            traced_model.train()

    if args.modelpath:
        torch.save(traced_model.state_dict(), args.modelpath)


if __name__ == "__main__":
    # Logging setup
    FORMAT = "%(asctime)s | %(message)s"
    logging.basicConfig(format=FORMAT)
    logger.setLevel(level=logging.DEBUG)

    # Websockets setup
    websockets_logger = logging.getLogger("websockets")
    websockets_logger.setLevel(logging.INFO)
    websockets_logger.addHandler(logging.StreamHandler())

    # Run main
    asyncio.get_event_loop().run_until_complete(main())
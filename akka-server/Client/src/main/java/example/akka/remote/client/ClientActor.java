package example.akka.remote.client;

import akka.actor.*;
import akka.event.Logging;
import akka.event.LoggingAdapter;
import example.akka.remote.shared.Messages;
import scala.concurrent.duration.FiniteDuration;

import java.io.*;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

public class ClientActor extends UntypedActor {

    public ClientActor() {
        try {
            // Getting configuration
            Configuration configurationHandler = new Configuration();
            Configuration.ConfigurationDTO configuration = configurationHandler.get();

            // Setting configuration
            this.address = configuration.address;
            this.pathToModules = configuration.pathToModules;
            this.port = configuration.port;
            this.clientId = configuration.id;

            // Getting the other actors
            // // flserver.eastus.azurecontainer.io:5000 - azure address
            this.selection = getContext().actorSelection("akka.tcp://AkkaRemoteServer@" + address + "/user/Selector");
            this.injector = getContext().actorSelection("akka.tcp://AkkaRemoteServer@" + address + "/user/Injector");
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private LoggingAdapter log = Logging.getLogger(getContext().system(), this);

    private String address;
    private String pathToModules;
    private int port;
    private String clientId;
    private String taskId;
    private String moduleFileName;

    private ActorSelection selection;
    private ActorSelection injector;

    @Override
    public void onReceive(Object message) throws Exception {
        // Message received at the beginning from main class
        if (message instanceof Messages.StartLearning) {
            this.taskId = ((Messages.StartLearning) message).id;

            // Finding proper module for specified task id
            List<ModulesManager.ModuleDTO> modules = ModulesManager.GetAvailableModules();

            ModulesManager.ModuleDTO module = modules
                    .stream()
                    .filter(x -> x.taskId.equals(this.taskId))
                    .findFirst()
                    .orElse(null);

            if (module == null) {
                // if module not found then ask for modules list
                injector.tell(new Messages.GetModulesListRequest(((Messages.StartLearning) message).id), getSelf());
                return;
            }
            // Set module filename
            this.moduleFileName = module.fileName;
            // When we confirm that we have module we can ask server to join round
            selection.tell(new Messages.JoinRoundRequest(LocalDateTime.now(), this.taskId, this.clientId, this.port), getSelf());
            log.info("After send to selector, address -> " + this.address);
        } else if(message instanceof Messages.GetModulesListResponse) {
            // Find the best module
            Messages.ModuleData module = this.findProperModuleStrategy(((Messages.GetModulesListResponse) message).modules);
            // Ask for module
            getSender().tell(new Messages.GetModuleRequest(module.fileName), getSelf());
        } else if (message instanceof Messages.GetModuleResponse) {
            // Save received module
            Messages.GetModuleResponse module = (Messages.GetModuleResponse) message;
            log.info("File name: " + module.fileName + ", length: " + module.content.length);
            SaveFile(module);
            log.info("File saved");
            ModulesManager.SaveModule(this.taskId, module.fileName);
            log.info("Module list saved");
            this.moduleFileName = module.fileName;
            selection.tell(new Messages.JoinRoundRequest(LocalDateTime.now(), this.taskId, this.clientId, this.port), getSelf());
        } else if (message instanceof Messages.JoinRoundResponse) {
            // Response if device can join round
            Messages.JoinRoundResponse result = (Messages.JoinRoundResponse) message;
            log.info("Got join round response {}", result.isLearningAvailable);
            // TODO Need to be handled negative scenario
        } else if (message instanceof Messages.StartLearningProcessCommand) {
            // Server told that device should run learning module
            log.info("Received start learning command");

            ActorSystem system = getContext().system();

            // Start learning module
            ActorRef moduleRummer = system.actorOf(Props.create(ClientRunModuleActor.class), "ClientRunModuleActor");
            moduleRummer.tell(new RunModule(this.moduleFileName), getSelf());

            ActorRef server = getSender();
            FiniteDuration delay =  new FiniteDuration(60, TimeUnit.SECONDS);

            // Tell server, after 60 sec, that script has been ran
            system
                .scheduler()
                .scheduleOnce(delay, server, new Messages.StartLearningModule(), system.dispatcher(), getSelf());
        }
    }

    // Saves file - module
    private void SaveFile(Messages.GetModuleResponse result) {
        try (FileOutputStream fos = new FileOutputStream(pathToModules + result.fileName)) {
            fos.write(result.content);
        } catch (Exception e) {
            log.info("Error:");
            e.printStackTrace();
        }
    }

    // Finds module that meets requirements
    private Messages.ModuleData findProperModuleStrategy(List<Messages.ModuleData> modules) throws Exception {
        try {
            Configuration configurationHandler = new Configuration();
            Configuration.ConfigurationDTO configuration = configurationHandler.get();

            Messages.ModuleData m = modules.stream().findFirst().get();
            Optional<Messages.ModuleData> moduleOpt = modules
                    .stream()
                    .filter(element ->
                            element.useCUDA.equals(configuration.useCuda)
                            && element.instanceType == configuration.instanceType
                            && element.minRAMInGB <= configuration.RAMInGB)
                    .findFirst();
            Messages.ModuleData module = moduleOpt.orElse(null);

            if (module == null) {
                throw new Exception("Could not find proper module");
            }
            return module;
        } catch (IOException e) {
            e.printStackTrace();
            throw e;
        }
    }

    // Run module message
    // TODO should be moved to messages
    public static class RunModule {
        public RunModule(String moduleFileName) {
            this.moduleFileName = moduleFileName;
        }
        public String moduleFileName;
    }
}

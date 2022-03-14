package example.akka.remote.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import example.akka.remote.shared.Messages;

import java.io.File;
import java.io.IOException;

public class Configuration {

    public static Integer dataSetId;  // number of dataset
    public static String id; // Id of the client e.g. alice
    public static Integer port; // port on which the client is working
    public static boolean diffPriv;
    public static double DP_std;

    // Method which saves arguments passed as execution arguments
    public void SaveArguments(String[] args) {
        System.out.println("Len: " + args.length);

        if (args.length > 1) {
            this.dataSetId = Integer.parseInt(args[1]);
        }
        if (args.length > 2) {
            this.id = args[2];
        }
        if (args.length > 3) {
            this.port = Integer.parseInt(args[3]);
        }
        if (args.length > 4) {
            double DP_std = Double.parseDouble( args[4] );

            if(DP_std <= 0){
                this.diffPriv = false;
                this.DP_std = 0;
            }
            else {
                this.diffPriv = true;
                this.DP_std = DP_std;
            }

        }
        System.out.println("dataSetId: " + this.dataSetId + ", id: " + this.id + ", port: " + this.port + ", DP: " + this.diffPriv + ", DP_std: " + this.DP_std);
    }

    // Method which returns configuration from appConfig.json file
    public ConfigurationDTO get() throws IOException {
        ObjectMapper mapper = new ObjectMapper();

        Configuration.ConfigurationDTO configuration = mapper.readValue(new File("./src/main/resources/appConfig.json"), Configuration.ConfigurationDTO.class);

        FillWithArguments(configuration);
        return configuration;
    }

    public void FillWithArguments(ConfigurationDTO configuration) {
        if (this.dataSetId != null) {
            System.out.println("dataSetId NOT NULL: " + this.dataSetId);
            configuration.dataSetId = this.dataSetId;
        } else {
            System.out.println("dataSetId NULL");
        }
        if (this.id != null) {
            configuration.id = this.id;
        }
        if (this.port != null) {
            configuration.port = this.port;
        } else {
            System.out.println("PORT IS NULL");
        }
        configuration.DP_std = this.DP_std;

    }

    public static class ConfigurationDTO {
        public Boolean useCuda;
        public int RAMInGB;
        public Messages.InstanceType instanceType;

        public String datapath;
        public String testdatapath;
        public String datafilename;
        public String targetfilename;
        public int epochs;
        public String id;
        public String host;
        public int port;
        public String address;
        public String pathToModules;
        public String pathToModulesList;
        public String pathToResources;
        public String pathToClientLearning;
        public String pathToInterRes;
        public String modelConfig;
        public String learningTaskId;
        public int dataSetId;
        public boolean diffPriv;
        public double DP_std;
    }
}



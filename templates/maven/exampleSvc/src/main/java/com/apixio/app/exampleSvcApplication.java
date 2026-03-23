package com.apixio.app;

import io.dropwizard.Application;
import io.dropwizard.setup.Bootstrap;
import io.dropwizard.setup.Environment;

public class exampleSvcApplication extends Application<exampleSvcConfiguration> {

    public static void main(final String[] args) throws Exception {
        new exampleSvcApplication().run(args);
    }

    @Override
    public String getName() {
        return "exampleSvc";
    }

    @Override
    public void initialize(final Bootstrap<exampleSvcConfiguration> bootstrap) {
        // TODO: application initialization
    }

    @Override
    public void run(final exampleSvcConfiguration configuration,
                    final Environment environment) {
        // TODO: implement application
    }

}

package com.ruanzhu.doorhandle.module.detection.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.scheduling.annotation.ScheduledAnnotationBeanPostProcessor;

import static org.assertj.core.api.Assertions.assertThat;

class DetectionDispatchSchedulingTest {

    private final ApplicationContextRunner context = new ApplicationContextRunner()
            .withUserConfiguration(DetectionDispatchScheduling.class);

    @Test
    void detectionCommandsEnableSchedulingWithoutTheAgentJournal() {
        context.withPropertyValues("detection.commands.enabled=true", "agentscope.journal.enabled=false")
                .run(application -> assertThat(application).hasSingleBean(ScheduledAnnotationBeanPostProcessor.class));
    }

    @Test
    void disabledCommandsDoNotEnableScheduling() {
        context.withPropertyValues("detection.commands.enabled=false")
                .run(application -> assertThat(application).doesNotHaveBean(ScheduledAnnotationBeanPostProcessor.class));
    }
}

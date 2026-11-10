package com.ruanzhu.doorhandle.module.system.config;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import com.ruanzhu.doorhandle.contracts.security.QualityAssigneeDirectory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Keep the Java domain contract independent of JSON, while preserving 64-bit IDs on the wire. */
@Configuration
@ConditionalOnProperty(prefix="collaboration.mutations",name="enabled",havingValue="true")
public class CollaborationJsonConfiguration {
    abstract static class AssigneeJson {
        @JsonSerialize(using=ToStringSerializer.class) public abstract Long userId();
    }
    @Bean public Jackson2ObjectMapperBuilderCustomizer collaborationIdentityJson() {
        return builder -> builder.mixIn(QualityAssigneeDirectory.Option.class,AssigneeJson.class);
    }
}

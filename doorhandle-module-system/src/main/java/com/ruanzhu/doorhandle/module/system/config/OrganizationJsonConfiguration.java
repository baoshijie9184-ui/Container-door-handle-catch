package com.ruanzhu.doorhandle.module.system.config;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi.DepartmentIdentity;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Preserve database BIGINT revisions without adding JSON dependencies to domain contracts. */
@Configuration
public class OrganizationJsonConfiguration {
    abstract static class DepartmentJson {
        @JsonSerialize(using=ToStringSerializer.class) public abstract Long version();
    }
    @Bean public Jackson2ObjectMapperBuilderCustomizer organizationIdentityJson() {
        return builder -> builder.mixIn(DepartmentIdentity.class,DepartmentJson.class);
    }
}

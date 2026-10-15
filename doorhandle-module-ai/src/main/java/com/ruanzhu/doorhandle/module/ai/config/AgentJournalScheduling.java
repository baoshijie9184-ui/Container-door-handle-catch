package com.ruanzhu.doorhandle.module.ai.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;

@Configuration
@EnableScheduling
@ConditionalOnProperty(prefix="agentscope.journal",name="enabled",havingValue="true")
public class AgentJournalScheduling {}

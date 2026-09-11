package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentGraphHealthResponse;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentGraphRunListener;

public interface AgentGraphRunMonitor extends AgentGraphRunListener {

    AgentGraphHealthResponse snapshot();
}

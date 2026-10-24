package com.ruanzhu.doorhandle.contracts.agent;

import java.util.Map;

/** Supervisor-only technical image DTOs. No process identity, private paths or credentials cross this facade. */
public interface AgentMcpImagesApi {
    Map<String,Object> view(AgentActor actor);
    Map<String,Object> cleanup(AgentActor actor,String image,int expected,String request,boolean confirmed);
    Map<String,Object> reconcile(AgentActor actor,String image,int expected,String request,boolean confirmed);
}

package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;

/** Business module owns each authorization and file mapping; no OSS keys leave the facade. */
public interface AgentBusinessFilesApi {
    record Resource(String kind,String resourceId,String fileId,String name,String contentType,String previewPath) {}
    record Delivery(String redirect,String text,String contentType) {}
    List<Resource> list(AgentActor actor,String kind,String resourceId);
    Delivery read(AgentActor actor,String kind,String resourceId,String fileId);
}

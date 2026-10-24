package com.ruanzhu.doorhandle.module.ai.mcp;

import java.util.*;

/** Reviewed package versions are code-owned; image allowlists are deployment-owned, never model input. */
final class FetchReleasePolicy {
    private final LocalMcpProperties properties;
    private final Set<String> images;
    FetchReleasePolicy(LocalMcpProperties properties){
        this.properties=properties;var approved=new LinkedHashSet<String>();
        if(properties.isGateway())approved.add(properties.getGatewayImage());
        approved.addAll(properties.getApprovedGatewayImages());
        if(approved.size()>8||approved.stream().anyMatch(value->value==null||!value.matches("sha256:[a-f0-9]{64}")))throw new IllegalStateException("MCP_RELEASE_ALLOWLIST_INVALID");
        images=Collections.unmodifiableSet(approved);
    }
    boolean approved(Map<String,Object> manifest){
        if(!FetchMcpRuntime.VERSION.equals(manifest.get("version"))||!FetchMcpRuntime.SHA.equals(manifest.get("packageSha256")))return false;
        return properties.isGateway()?"STREAMABLE_HTTP".equals(manifest.get("transport"))&&images.contains(manifest.get("image")):"STDIO".equals(manifest.get("transport"));
    }
    boolean target(Map<String,Object> manifest){return approved(manifest)&&(!properties.isGateway()||properties.getGatewayImage().equals(manifest.get("image")));}
    Map<String,Object> view(){return Map.of("packageVersion",FetchMcpRuntime.VERSION,"packageSha256",FetchMcpRuntime.SHA,"transport",properties.isGateway()?"STREAMABLE_HTTP":"STDIO","image",properties.isGateway()?properties.getGatewayImage():"","approvedImages",images);}
}

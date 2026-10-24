package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;

/** Business module owns each authorization and file mapping; no OSS keys leave the facade. */
public interface AgentBusinessFilesApi {
    record Resource(String kind,String resourceId,String fileId,String name,String contentType,String previewPath) {}
    /** Stable metadata fingerprint shared by the producer and context authorization adapter. */
    static String contextVersion(Resource resource){
        try{
            var digest=java.security.MessageDigest.getInstance("SHA-256");
            for(String value:new String[]{resource.kind(),resource.resourceId(),resource.fileId(),resource.name(),resource.contentType(),resource.previewPath()}){
                byte[] bytes=java.util.Objects.toString(value,"").getBytes(java.nio.charset.StandardCharsets.UTF_8);
                digest.update(java.nio.ByteBuffer.allocate(4).putInt(bytes.length).array());digest.update(bytes);
            }
            return java.util.HexFormat.of().formatHex(digest.digest());
        }catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
    }
    record Delivery(String redirect,String text,String contentType) {}
    /** Internal bounded bytes, never returned directly by the browser resource controller. */
    record OriginalImage(String taskId,String name,String contentType,byte[] content,String resourceVersion) {}
    List<Resource> list(AgentActor actor,String kind,String resourceId);
    List<Resource> originalImages(AgentActor actor,String taskId);
    Delivery read(AgentActor actor,String kind,String resourceId,String fileId);
    default OriginalImage readOriginal(AgentActor actor,String taskId,String fileId,long maxBytes){throw new UnsupportedOperationException("Original image bytes unavailable");}
    default void assertOriginal(AgentActor actor,String taskId,String fileId,String resourceVersion){throw new UnsupportedOperationException("Original image reference validation unavailable");}
}

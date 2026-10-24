package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;

/** Only account/session-authorized image IDs cross this boundary; never local paths or OSS URLs. */
public interface WorkspaceDetectionImagesApi {
    record BusinessReference(String taskId,String fileId) {}
    record Origin(String taskId,String fileId,String resourceVersion) {}
    record Image(String fileId,String name,String contentType,long bytes,String sha256,String previewPath,Origin origin) {
        public Image(String fileId,String name,String contentType,long bytes,String sha256,String previewPath){this(fileId,name,contentType,bytes,sha256,previewPath,null);}
    }
    List<Image> describe(AgentActor actor,String sessionId,List<String> fileIds);
    default List<Image> describeBusiness(AgentActor actor,String sessionId,List<BusinessReference> references){throw new UnsupportedOperationException("Business image references unavailable");}
    /** Only local metadata and business authorization checks; never performs network I/O under approval locks. */
    default void assertUnchanged(AgentActor actor,String sessionId,List<Image> expected){
        if(!describe(actor,sessionId,expected.stream().map(Image::fileId).toList()).equals(expected))throw new IllegalStateException("Image sources changed");
    }
    byte[] read(AgentActor actor,String sessionId,Image expected);
}

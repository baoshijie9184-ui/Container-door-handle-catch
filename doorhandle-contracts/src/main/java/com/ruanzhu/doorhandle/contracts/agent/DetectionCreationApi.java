package com.ruanzhu.doorhandle.contracts.agent;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

/** Reserve only after persisted human approval; actual OSS transfer runs outside the approval transaction. */
public interface DetectionCreationApi {
    record Capture(String captureDate,String region,String collector,String deviceName,String imageFolderName) {}
    record Request(List<String> fileIds,Integer modelId,BigDecimal threshold,Capture capture,List<WorkspaceDetectionImagesApi.BusinessReference> businessImages) {
        public Request(List<String> fileIds,Integer modelId,BigDecimal threshold,Capture capture){this(fileIds,modelId,threshold,capture,List.of());}
        public Request{fileIds=fileIds==null?List.of():List.copyOf(fileIds);businessImages=businessImages==null?List.of():List.copyOf(businessImages);}
    }
    record Preview(String sessionId,List<WorkspaceDetectionImagesApi.Image> images,DetectionModelSelectionApi.Model model,
                   BigDecimal threshold,Capture capture,String resourceVersion) {}
    record Receipt(String commandId,String taskId,String dispatchId,String status) {}
    /** Minimal owner-scoped view; source filenames, paths and credentials are never returned here. */
    record TransferReview(String commandId,String taskId,String status,long revision,int images,int acknowledged,
                          boolean manifestAvailable,String checkId,String checkStatus,int checked,int verified,
                          boolean canFinalize,String reasonCode,String checkedAt) {}
    record ReviewCommand(String requestId,long revision,String action,String checkId) {}
    Preview preview(AgentActor actor,String sessionId,Request request);
    Receipt reserve(AgentActor actor,String requestId,String proposalId,Preview approved);
    Optional<Receipt> receipt(AgentActor actor,String requestId);
    List<Receipt> jobs(AgentActor actor,String sessionId,int limit);
    void assertReadable(AgentActor actor,Preview approved);
    default List<TransferReview> transferReviews(AgentActor actor,String sessionId){return List.of();}
    default TransferReview reviewTransfer(AgentActor actor,String sessionId,String commandId,ReviewCommand command){throw new UnsupportedOperationException("Transfer review unavailable");}
    default void revalidate(AgentActor actor,Preview approved){if(!preview(actor,approved.sessionId(),requestFor(approved)).equals(approved))throw new DetectionExecutionApi.ResourceChanged();}
    static Request requestFor(Preview approved){return new Request(approved.images().stream().filter(image->image.origin()==null).map(WorkspaceDetectionImagesApi.Image::fileId).toList(),approved.model().id(),approved.threshold(),approved.capture(),approved.images().stream().filter(image->image.origin()!=null).map(image->new WorkspaceDetectionImagesApi.BusinessReference(image.origin().taskId(),image.origin().fileId())).toList());}
}

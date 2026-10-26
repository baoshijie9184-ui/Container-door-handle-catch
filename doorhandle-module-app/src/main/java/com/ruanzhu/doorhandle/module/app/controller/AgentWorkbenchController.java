package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.service.impl.AgentWorkspaceService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

@RestController
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class AgentWorkbenchController {
    private final AgentWorkbenchApi workbench;private final AgentWorkspaceService workspace;
    private final org.springframework.beans.factory.ObjectProvider<DetectionCreationApi> creation;
    public AgentWorkbenchController(AgentWorkbenchApi workbench,AgentWorkspaceService workspace){this(workbench,workspace,null);}
    @org.springframework.beans.factory.annotation.Autowired
    public AgentWorkbenchController(AgentWorkbenchApi workbench,AgentWorkspaceService workspace,org.springframework.beans.factory.ObjectProvider<DetectionCreationApi> creation){this.workbench=workbench;this.workspace=workspace;this.creation=creation;}
    @ModelAttribute void privacy(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    private AgentActor actor(Authentication auth,String session){if(auth==null||!auth.isAuthenticated()||!(auth.getPrincipal() instanceof TenantPrincipal user))throw fail(401,"请先登录");var roles=auth.getAuthorities().stream().map(value->value.getAuthority()).toList();var role=roles.contains("ROLE_SUPERVISOR")?AgentActor.Role.SUPERVISOR:roles.contains("ROLE_INSPECTOR")?AgentActor.Role.INSPECTOR:null;if(role==null)throw fail(403,"当前账号无工作台权限");var actor=new AgentActor(user.userId(),user.username(),role);if(session!=null)workspace.assertOwned(actor,session);return actor;}
    private void mutation(HttpServletRequest request){if(!"workbench".equals(request.getHeader("X-Agent-Action"))||"cross-site".equals(request.getHeader("Sec-Fetch-Site")))throw fail(403,"工作台请求无效");}
    private void feature(String key){if(!Boolean.TRUE.equals(workbench.capabilities().get(key)))throw fail(409,"此能力尚未启用");}
    @GetMapping("/api/agent/workbench/capabilities") public Object capabilities(Authentication auth){actor(auth,null);var capabilities=new java.util.LinkedHashMap<String,Boolean>(workbench.capabilities());capabilities.put("detectionCreationReviews",Boolean.TRUE.equals(capabilities.get("enabled"))&&creation!=null&&creation.getIfAvailable()!=null);return capabilities;}
    @GetMapping("/api/agent/conversations/{session}/workbench") public ResponseEntity<?> view(Authentication auth,@PathVariable String session){var actor=actor(auth,session);boolean files=Boolean.TRUE.equals(workbench.capabilities().get("files"));return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(Map.of("items",workbench.list(actor,session),"files",files?workspace.files(actor,session):java.util.List.of(),"businessFiles",files?workspace.businessFiles(actor,session):java.util.List.of(),"lineage",workspace.lineage(actor,session),"limits",workspace.limits()));}
    public record Command(@NotBlank @Size(max=128) String requestId,@Min(0) long revision,@NotBlank String action,Map<String,Object> input){}
    @PostMapping("/api/agent/conversations/{session}/workbench/{id}") public Object command(Authentication auth,@PathVariable String session,@PathVariable String id,@Valid @RequestBody Command body,HttpServletRequest request){mutation(request);return workbench.command(actor(auth,session),session,id,body.revision(),body.requestId(),body.action(),body.input());}
    @PostMapping("/api/agent/conversations/{session}/files") public Object upload(Authentication auth,@PathVariable String session,@RequestParam String requestId,@RequestParam MultipartFile file,HttpServletRequest request)throws java.io.IOException{mutation(request);feature("files");if(file.getSize()>workspace.limits().get("maxFileBytes"))throw fail(413,"文件超过账号配置的单文件上限");return workspace.upload(actor(auth,session),session,requestId,file.getOriginalFilename(),file.getBytes(),"uploads");}
    @FileDelivery(domain="WORKSPACE_FILE",resource="arg2",scope="PRIVATE")
    @GetMapping("/api/agent/conversations/{session}/files/{id}/content") public ResponseEntity<byte[]> content(Authentication auth,@PathVariable String session,@PathVariable String id){feature("files");var actor=actor(auth,session);var file=workspace.requireFile(actor,session,id);return ResponseEntity.ok().cacheControl(CacheControl.noStore()).header("X-Content-Type-Options","nosniff").header("Content-Security-Policy","default-src 'none'; sandbox").header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(file.name(),StandardCharsets.UTF_8).build().toString()).contentType(MediaType.parseMediaType(file.contentType())).body(workspace.bytes(actor,session,id));}
    @PostMapping("/api/agent/conversations/{session}/files/{id}/remove") public Object remove(Authentication auth,@PathVariable String session,@PathVariable String id,@Valid @RequestBody Remove body,HttpServletRequest request){mutation(request);feature("files");workspace.remove(actor(auth,session),session,id,body.requestId());return Map.of("removed",true);}
    @FileDelivery(domain="WORKSPACE_PREVIEW",resource="arg2",scope="PRIVATE")
    @GetMapping("/api/agent/conversations/{session}/files/{id}/preview") public ResponseEntity<byte[]> preview(Authentication auth,@PathVariable String session,@PathVariable String id,@RequestParam(defaultValue="1") int page){feature("files");var preview=workspace.previewPdf(actor(auth,session),session,id,page);return ResponseEntity.ok().cacheControl(CacheControl.noStore()).header("X-Content-Type-Options","nosniff").header("Content-Security-Policy","default-src 'none'; sandbox").header("X-PDF-Page",Integer.toString(preview.page())).header("X-PDF-Pages",Integer.toString(preview.pages())).contentType(MediaType.IMAGE_PNG).body(preview.png());}
    public record Remove(@NotBlank String requestId){}
    @FileDelivery(domain="WORKSPACE_IMAGE",resource="arg2",scope="PRIVATE")
    @GetMapping("/api/agent/conversations/{session}/files/{id}/image") public ResponseEntity<byte[]> image(Authentication auth,@PathVariable String session,@PathVariable String id){
        feature("files");var actor=actor(auth,session);var file=workspace.requireFile(actor,session,id);
        if(!java.util.Set.of("image/jpeg","image/png").contains(file.contentType()))throw fail(415,"此接口仅预览 JPEG/PNG 图片");
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).header("X-Content-Type-Options","nosniff")
                .header("Content-Security-Policy","default-src 'none'; sandbox").header(HttpHeaders.CONTENT_DISPOSITION,"inline")
                .contentType(MediaType.parseMediaType(file.contentType())).body(workspace.bytes(actor,session,id));
    }
    public record BusinessFile(@NotBlank String requestId,@NotBlank String kind,@NotBlank @Size(max=128) String resourceId){}
    @PostMapping("/api/agent/conversations/{session}/business-files") public Object attachBusiness(Authentication auth,@PathVariable String session,@Valid @RequestBody BusinessFile body,HttpServletRequest request){mutation(request);feature("files");return workspace.attachBusinessFiles(actor(auth,session),session,body.requestId(),body.kind(),body.resourceId());}
    public record Fork(@NotBlank String requestId,@Min(1) long throughMessageId){}
    @PostMapping("/api/agent/conversations/{session}/fork") public Object fork(Authentication auth,@PathVariable String session,@Valid @RequestBody Fork body,HttpServletRequest request){mutation(request);feature("forks");var actor=actor(auth,session);workbench.assertForkPoint(actor,session,body.throughMessageId());String child=workspace.fork(actor,session,body.throughMessageId(),body.requestId());workbench.forked(actor,session,child,body.throughMessageId());return Map.of("sessionId",child,"sourceSessionId",session);}
    @ExceptionHandler(ResponseStatusException.class) ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).cacheControl(CacheControl.noStore()).body(Map.of("message",error.getReason()==null?"请求无效":error.getReason()));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) ResponseEntity<?> denied(){return ResponseEntity.status(403).cacheControl(CacheControl.noStore()).body(Map.of("message","当前账号无法执行此操作"));}
    @ExceptionHandler(org.springframework.dao.DataAccessException.class) ResponseEntity<?> unavailable(){return ResponseEntity.status(503).cacheControl(CacheControl.noStore()).body(Map.of("message","工作台存储暂不可用，请核对结果，不会自动重试"));}
    @ExceptionHandler(com.ruanzhu.doorhandle.common.BusinessException.class) ResponseEntity<?> business(com.ruanzhu.doorhandle.common.BusinessException error){return ResponseEntity.status(error.getCode()>=400&&error.getCode()<600?error.getCode():400).cacheControl(CacheControl.noStore()).body(Map.of("message",error.getMessage()));}
    private static ResponseStatusException fail(int status,String text){return new ResponseStatusException(HttpStatus.valueOf(status),text);}
}

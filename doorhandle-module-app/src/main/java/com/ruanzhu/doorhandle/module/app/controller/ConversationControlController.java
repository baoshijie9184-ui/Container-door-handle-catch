package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.app.service.impl.ConversationInboxService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController
@RequestMapping("/api/agent/conversations")
public class ConversationControlController {
    private final ObjectProvider<ConversationInboxService> inbox;
    private final ObjectProvider<AgentConversationControlApi> control;
    private final ChatSessionService sessions;
    public ConversationControlController(ObjectProvider<ConversationInboxService> inbox,ObjectProvider<AgentConversationControlApi> control,ChatSessionService sessions){this.inbox=inbox;this.control=control;this.sessions=sessions;}
    @ModelAttribute void privacy(HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    private AgentActor actor(Authentication auth,String session){
        if(auth==null||!auth.isAuthenticated()||!(auth.getPrincipal() instanceof TenantPrincipal principal))throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"请先登录");
        var role=auth.getAuthorities().stream().anyMatch(a->"ROLE_SUPERVISOR".equals(a.getAuthority()))?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR;
        if(auth.getAuthorities().stream().noneMatch(a->a.getAuthority().equals("ROLE_"+role.name())))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"当前账号无 Agent 权限");
        if(session!=null)sessions.verifySessionOwner(principal.username(),session);
        return new AgentActor(principal.userId(),principal.username(),role);
    }
    private ConversationInboxService inbox(){var value=inbox.getIfAvailable();if(value==null)throw new ResponseStatusException(HttpStatus.CONFLICT,"此环境尚未启用对话控制");return value;}
    private void mutation(HttpServletRequest request){if(!"conversation-control".equals(request.getHeader("X-Agent-Action"))||"cross-site".equals(request.getHeader("Sec-Fetch-Site")))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"执行控制请求无效");}
    @GetMapping("/capabilities") public Map<String,Object> capabilities(Authentication auth){actor(auth,null);return Map.of("enabled",inbox.getIfAvailable()!=null&&control.getIfAvailable()!=null,"pauseMode","LIVE_SAFE_BOUNDARY","maxRunSeconds",control.getIfAvailable()==null?180:control.getObject().maxRunSeconds());}
    @GetMapping("/{session}/control") public Object view(Authentication auth,@PathVariable String session){var actor=actor(auth,session);var entries=inbox().list(actor,session);return Map.of("run",control.getObject().inspect(actor,session),"inputs",entries);}
    public record Enqueue(@NotBlank String id,@NotBlank String mode,@NotBlank @Size(max=8000) String content,String entryPoint){}
    @PostMapping("/{session}/inputs") public Object enqueue(Authentication auth,@PathVariable String session,@Valid @RequestBody Enqueue input,HttpServletRequest request){mutation(request);return inbox().enqueue(actor(auth,session),session,input.id(),input.mode(),input.content(),input.entryPoint()==null?"CHAT":input.entryPoint());}
    public record Change(@Min(0) int revision,@Size(max=8000) String content){}
    @PostMapping("/{session}/inputs/{id}") public Object change(Authentication auth,@PathVariable String session,@PathVariable String id,@Valid @RequestBody Change input,HttpServletRequest request){mutation(request);return inbox().change(actor(auth,session),session,id,input.revision(),input.content());}
    public record Command(@NotBlank String runId,@NotBlank String action,@Min(0) long revision,boolean confirmed){}
    public record Steer(@NotBlank @Size(max=128) String runId,@Min(0) int revision){}
    @PostMapping("/{session}/inputs/{id}/steer") public Object steer(Authentication auth,@PathVariable String session,@PathVariable String id,@Valid @RequestBody Steer input,HttpServletRequest request){mutation(request);return inbox().steer(actor(auth,session),session,id,input.revision(),input.runId());}
    @PostMapping("/{session}/control") public Object command(Authentication auth,@PathVariable String session,@Valid @RequestBody Command input,HttpServletRequest request){
        mutation(request);var actor=actor(auth,session);inbox().list(actor,session);
        if("cancel".equals(input.action())&&!input.confirmed())throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"请确认取消本轮任务");
        return control.getObject().command(actor,session,input.runId(),input.action(),input.revision());
    }
    @ExceptionHandler(ResponseStatusException.class) ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).header("Cache-Control","no-store").body(Map.of("message",error.getReason()==null?"请求无效":error.getReason()));}
    @ExceptionHandler(com.ruanzhu.doorhandle.common.BusinessException.class) ResponseEntity<?> business(com.ruanzhu.doorhandle.common.BusinessException error){int code=error.getCode();return ResponseEntity.status(code>=400&&code<600?code:400).header("Cache-Control","no-store").body(Map.of("message",error.getMessage()));}
    @ExceptionHandler(org.springframework.dao.DataAccessException.class) ResponseEntity<?> unavailable(){return ResponseEntity.status(503).header("Cache-Control","no-store").body(Map.of("message","对话控制存储暂不可用，请刷新核对，不会自动重试"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) ResponseEntity<?> forbidden(){return ResponseEntity.status(403).header("Cache-Control","no-store").body(Map.of("message","当前身份无法使用对话控制"));}
}

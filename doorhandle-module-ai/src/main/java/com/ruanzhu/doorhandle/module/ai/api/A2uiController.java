package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.ui.A2uiService;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(prefix="agentscope.ai",name="enabled",havingValue="true")
@RequestMapping("${agentscope.agui.path-prefix:/agui}/ui")
public class A2uiController {
    private final A2uiService service;
    public A2uiController(A2uiService service){this.service=service;}
    @PostMapping("/resolve") public ResponseEntity<?> resolve(Authentication auth,@RequestBody A2uiService.Query query){return ResponseEntity.ok().header("Cache-Control","no-store").body(service.resolve(AgentIdentity.from(auth),query));}
    /** Prepare a bounded user follow-up; the client still submits through existing admission. */
    @PostMapping("/actions") public ResponseEntity<?> action(Authentication auth,@RequestHeader(value="X-Agent-Action",defaultValue="") String header,@RequestBody A2uiService.Interaction input){
        if(!"a2ui".equals(header))throw new IllegalArgumentException();
        return ResponseEntity.ok().header("Cache-Control","no-store").body(Map.of("question",service.followUp(AgentIdentity.from(auth),input)));
    }
    @ExceptionHandler({IllegalArgumentException.class,org.springframework.http.converter.HttpMessageNotReadableException.class}) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","动态界面或操作参数无效"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前账号无权读取或操作此界面"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","动态界面暂不可用，聊天记录仍可阅读"));}
}

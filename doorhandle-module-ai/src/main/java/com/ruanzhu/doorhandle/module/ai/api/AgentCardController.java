package com.ruanzhu.doorhandle.module.ai.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.ruanzhu.doorhandle.contracts.agent.AgentCards;
import com.ruanzhu.doorhandle.module.ai.card.AgentCardService;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/agent/cards")
@Tag(name="Agent 业务卡片",description="只读解析当前权限下的业务引用，不调用模型或执行写工具")
public class AgentCardController {
    private final AgentCardService service;
    public AgentCardController(AgentCardService service){this.service=service;}
    @PostMapping("/resolve") public ResponseEntity<?> resolve(Authentication auth,@RequestBody JsonNode body) {
        var actor=AgentIdentity.from(auth);
        if(!body.isObject()||body.size()!=1||!body.has("cards")||!body.path("cards").isArray()||body.path("cards").size()>8)
            throw new IllegalArgumentException();
        var refs=new ArrayList<AgentCards.Reference>();
        for(JsonNode card:body.path("cards")) {
            if(!card.isObject())throw new IllegalArgumentException();
            card.fieldNames().forEachRemaining(key->{if(!Set.of("type","tool","ids","days").contains(key))throw new IllegalArgumentException();});
            if(!card.path("type").isTextual()||!card.path("tool").isTextual()||!card.path("ids").isArray()||card.path("ids").size()>5)throw new IllegalArgumentException();
            var ids=new ArrayList<String>();for(JsonNode id:card.path("ids")){if(!id.isTextual())throw new IllegalArgumentException();ids.add(id.asText());}
            var days=card.path("days");if(!days.isMissingNode()&&!days.isNull()&&(!days.isIntegralNumber()||!days.canConvertToInt()))throw new IllegalArgumentException();
            refs.add(new AgentCards.Reference(card.path("type").asText(),card.path("tool").asText(),ids,days.isMissingNode()||days.isNull()?null:days.intValue()));
        }
        return ResponseEntity.ok().header("Cache-Control","no-store").body(Map.of("cards",service.resolve(actor,refs)));
    }
    @ExceptionHandler(IllegalArgumentException.class) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","卡片类型或参数不合法"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class})
    public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前身份无权读取卡片"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","卡片数据暂不可用"));}
}

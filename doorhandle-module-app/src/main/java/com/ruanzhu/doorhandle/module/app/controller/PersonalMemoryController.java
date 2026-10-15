package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.system.security.*;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/agent/memories")
@RequiredArgsConstructor
public class PersonalMemoryController {
    private final PersonalMemoryService memory;
    private final MemoryPreferenceService preferences;
    @ModelAttribute public void noCache(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    private TenantContext owner(Authentication auth) {
        if(auth==null||!auth.isAuthenticated()||!(auth.getPrincipal() instanceof TenantPrincipal principal))throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"请先登录检测系统");
        if(auth.getAuthorities().stream().noneMatch(a->java.util.Set.of("ROLE_INSPECTOR","ROLE_SUPERVISOR").contains(a.getAuthority())))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"当前账号没有助手权限");
        return new TenantContext(principal.userId(),principal.username());
    }
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> rejected(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()==null?"请求无效":error.getReason()));}
    @ExceptionHandler(org.springframework.web.bind.MethodArgumentNotValidException.class) public ResponseEntity<?> invalidBody(){return ResponseEntity.badRequest().body(Map.of("message","请核对版本、正文长度并明确确认操作"));}
    @ExceptionHandler(org.springframework.dao.DataAccessException.class) public ResponseEntity<?> storageUnavailable(){return ResponseEntity.status(503).body(Map.of("message","记忆设置或审计存储暂不可用；如已提交修改或删除，请刷新核对结果"));}
    @GetMapping public MemoryDtos.Page list(Authentication auth,@RequestParam(defaultValue="50")int limit,@RequestParam(defaultValue="0")int offset){return offset==0?memory.list(owner(auth),limit):memory.list(owner(auth),limit,offset);}
    @GetMapping("/preferences") public MemoryDtos.Preference preferences(Authentication auth){return preferences.get(owner(auth));}
    @PutMapping("/preferences") public MemoryDtos.Preference change(Authentication auth,@Valid @RequestBody MemoryDtos.ChangePreference request){return preferences.change(owner(auth),request);}
    @PostMapping("/{id}/delete") public MemoryDtos.Deleted delete(Authentication auth,@PathVariable String id,@Valid @RequestBody MemoryDtos.Delete request){return memory.delete(owner(auth),id,request);}
    @PostMapping("/{id}/update") public MemoryDtos.Updated update(Authentication auth,@PathVariable String id,@Valid @RequestBody MemoryDtos.Update request){return memory.update(owner(auth),id,request);}
    @GetMapping("/audit") public List<MemoryDtos.Audit> audit(Authentication auth){return preferences.audit(owner(auth));}
    @GetMapping("/{id}") public MemoryDtos.Item get(Authentication auth,@PathVariable String id){return memory.get(owner(auth),id);}
}

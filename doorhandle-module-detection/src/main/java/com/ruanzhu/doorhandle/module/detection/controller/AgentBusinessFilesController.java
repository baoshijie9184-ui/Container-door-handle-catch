package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.net.URI;

@RestController
public class AgentBusinessFilesController {
    private final AgentBusinessFilesApi files;private final BusinessUserDirectory users;
    public AgentBusinessFilesController(AgentBusinessFilesApi files,BusinessUserDirectory users){this.files=files;this.users=users;}
    @GetMapping("/api/agent/business-files/{kind}/{resource}/{file}") public ResponseEntity<?> read(Authentication auth,@PathVariable String kind,@PathVariable String resource,@PathVariable String file){
        if(auth==null||!auth.isAuthenticated()||!(auth.getPrincipal() instanceof TenantPrincipal user))throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        var identity=users.current(user.userId(),user.username());var actor=new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);var delivery=files.read(actor,kind,resource,file);
        if(delivery.redirect()!=null)return ResponseEntity.status(302).cacheControl(CacheControl.noStore()).location(URI.create(delivery.redirect())).build();
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).header("X-Content-Type-Options","nosniff").header("Content-Security-Policy","default-src 'none'; sandbox").contentType(MediaType.parseMediaType(delivery.contentType())).body(delivery.text());
    }
    @ExceptionHandler(SecurityException.class) ResponseEntity<?> denied(){return ResponseEntity.status(403).cacheControl(CacheControl.noStore()).build();}
    @ExceptionHandler(IllegalArgumentException.class) ResponseEntity<?> invalid(){return ResponseEntity.badRequest().cacheControl(CacheControl.noStore()).build();}
}

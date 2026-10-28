package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.app.service.knowledge.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;

@RestController
@RequestMapping("/api/quality/knowledge")
@ConditionalOnProperty(prefix="app.knowledge",name="enabled",havingValue="true")
public class QualityKnowledgeController {
    private final QualityKnowledgeService service;private final KnowledgeTextExtractor extractor;private final BusinessUserDirectory users;
    public QualityKnowledgeController(QualityKnowledgeService service,KnowledgeTextExtractor extractor,BusinessUserDirectory users){this.service=service;this.extractor=extractor;this.users=users;}
    @GetMapping public Result<Map<String,Object>> list(@RequestParam(defaultValue="1")int page,@RequestParam(defaultValue="20")int size,@RequestParam(defaultValue="")String keyword){return Result.success(service.list(users.authenticated(),page,size,keyword));}
    @GetMapping("/search") public Result<List<Map<String,Object>>> search(@RequestParam String query){return Result.success(service.search(users.authenticated(),query));}
    @GetMapping("/{id}") public Result<Map<String,Object>> detail(@PathVariable String id,@RequestParam(required=false)Integer version){return Result.success(service.revision(users.authenticated(),id,version));}
    @PostMapping(consumes=MediaType.MULTIPART_FORM_DATA_VALUE) public Result<Map<String,Object>> create(@RequestParam String title,@RequestParam(defaultValue="PRIVATE")String visibility,@RequestParam String requestId,@RequestPart MultipartFile file,@RequestHeader(value="X-Knowledge-Action",required=false)String marker)throws IOException{return upload(null,0,title,visibility,requestId,file,marker);}
    @PostMapping(value="/{id}/versions",consumes=MediaType.MULTIPART_FORM_DATA_VALUE) public Result<Map<String,Object>> version(@PathVariable String id,@RequestParam int expectedVersion,@RequestParam String title,@RequestParam String visibility,@RequestParam String requestId,@RequestPart MultipartFile file,@RequestHeader(value="X-Knowledge-Action",required=false)String marker)throws IOException{return upload(id,expectedVersion,title,visibility,requestId,file,marker);}
    private Result<Map<String,Object>> upload(String id,int version,String title,String visibility,String request,MultipartFile file,String marker)throws IOException{guard(marker);var actor=users.authenticated();if(file.getSize()>5L*1024*1024)throw new BusinessException(413,"原文件不超过 5 MiB");String name=Objects.toString(file.getOriginalFilename(),"资料.txt").replace('\\','/');name=name.substring(name.lastIndexOf('/')+1);if(name.isBlank()||name.length()>255||name.chars().anyMatch(c->c<32))throw new BusinessException(400,"文件名不正确");byte[] bytes=file.getBytes();var text=extractor.extract(name,bytes);return Result.success(service.write(actor,id,version,title,visibility,name,text,bytes,request));}
    public record Lifecycle(@Min(1)int expectedVersion,boolean archived,@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}")String requestId){}
    @PutMapping("/{id}/lifecycle") public Result<Map<String,Object>> lifecycle(@PathVariable String id,@Valid @RequestBody Lifecycle request,@RequestHeader(value="X-Knowledge-Action",required=false)String marker){guard(marker);return Result.success(service.archive(users.authenticated(),id,request.expectedVersion(),request.archived(),request.requestId()));}
    @GetMapping("/{id}/versions/{version}/source") public ResponseEntity<byte[]> source(@PathVariable String id,@PathVariable int version){var result=service.source(users.authenticated(),id,version);return ResponseEntity.ok().cacheControl(CacheControl.noStore()).contentType(MediaType.APPLICATION_OCTET_STREAM).header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(result.filename(),StandardCharsets.UTF_8).build().toString()).header("X-Content-SHA256",result.sha256()).header("X-Content-Type-Options","nosniff").body(result.bytes());}
    private static void guard(String value){if(!"update".equals(value))throw new BusinessException(400,"缺少资料操作标记");}
}

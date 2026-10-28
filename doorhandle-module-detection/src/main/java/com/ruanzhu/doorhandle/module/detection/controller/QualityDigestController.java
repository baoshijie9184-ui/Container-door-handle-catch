package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.module.detection.service.QualityDigestService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/quality/digests")
@ConditionalOnProperty(prefix="app.quality-automation",name="enabled",havingValue="true")
public class QualityDigestController {
    private final QualityDigestService service;
    public QualityDigestController(QualityDigestService service){this.service=service;}
    @GetMapping public Result<List<Map<String,Object>>> schedules(){return Result.success(service.schedules());}
    @PostMapping public Result<Map<String,Object>> create(@RequestBody QualityDigestService.Save request,@RequestHeader(value="X-Digest-Action",required=false)String marker){guard(marker);return Result.success(service.save(null,request));}
    @PutMapping("/{id}") public Result<Map<String,Object>> update(@PathVariable String id,@RequestBody QualityDigestService.Save request,@RequestHeader(value="X-Digest-Action",required=false)String marker){guard(marker);return Result.success(service.save(id,request));}
    @PostMapping("/{id}/runs") public Result<Map<String,Object>> generate(@PathVariable String id,@RequestBody QualityDigestService.Generate request,@RequestHeader(value="X-Digest-Action",required=false)String marker){guard(marker);return Result.success(service.generate(id,request));}
    @GetMapping("/{id}/runs") public Result<List<Map<String,Object>>> runs(@PathVariable String id){return Result.success(service.runs(id));}
    @PostMapping("/runs/{runId}/export") public ResponseEntity<byte[]> export(@PathVariable String runId,@RequestParam(defaultValue="md")String format,@RequestHeader(value="X-Digest-Action",required=false)String marker){guard(marker);var file=service.download(runId,format);return ResponseEntity.ok().cacheControl(CacheControl.noStore()).contentType(MediaType.parseMediaType(file.mediaType())).header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(runId+"."+file.extension()).build().toString()).header("X-Content-Type-Options","nosniff").body(file.bytes());}
    private static void guard(String marker){if(!"update".equals(marker))throw new BusinessException(400,"缺少日报操作标记");}
}

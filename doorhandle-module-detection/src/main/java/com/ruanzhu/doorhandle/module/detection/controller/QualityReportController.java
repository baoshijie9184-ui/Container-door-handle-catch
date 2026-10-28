package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.*;
import com.ruanzhu.doorhandle.module.detection.service.QualityReportService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.*;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

@RestController
@RequestMapping("/api/detection/reports")
@Tag(name="报告与审批",description="私人草稿、冻结提交、独立主管审批和已审批快照导出")
public class QualityReportController {
    private final QualityReportService service;
    public QualityReportController(QualityReportService service){this.service=service;}
    @GetMapping public Result<Map<String,Object>> list(@AuthenticationPrincipal TenantPrincipal principal,
            @RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size,
            @RequestParam(required=false) String status,@RequestParam(required=false) String keyword){return Result.success(service.list(actor(principal),page,size,status,keyword));}
    @GetMapping("/{id}") public Result<View> get(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id){return Result.success(service.get(actor(principal),id));}
    @GetMapping("/{id}/audit") public Result<List<Audit>> audit(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id){return Result.success(service.audit(actor(principal),id));}
    @GetMapping("/{id}/events") public ResponseEntity<Result<List<EventDelivery>>> events(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id){return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(Result.success(service.events(actor(principal),id)));}
    @PostMapping("/{id}/events/{eventId}/retry") @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<List<EventDelivery>> retryEvent(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,@PathVariable String eventId,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody RetryEvent request){guard(header);return Result.success(service.retryEvent(actor(principal),id,eventId,request));}
    @PostMapping public Result<View> create(@AuthenticationPrincipal TenantPrincipal principal,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody Create request){guard(header);return Result.success(service.create(actor(principal),request));}
    @PutMapping("/{id}") public Result<View> edit(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody Edit request){guard(header);return Result.success(service.edit(actor(principal),id,request));}
    @PostMapping("/{id}/submit") public Result<View> submit(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody Command request){guard(header);return Result.success(service.submit(actor(principal),id,request));}
    @PostMapping("/{id}/withdraw") public Result<View> withdraw(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody Command request){guard(header);return Result.success(service.withdraw(actor(principal),id,request));}
    @PostMapping("/{id}/revise") public Result<View> revise(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody Command request){guard(header);return Result.success(service.revise(actor(principal),id,request));}
    @PostMapping("/{id}/decision-preview") @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Preview> preview(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody DecisionPreview request){guard(header);return Result.success(service.preview(actor(principal),id,request));}
    @PostMapping("/{id}/decision") @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<View> decide(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@Valid @RequestBody Decision request){guard(header);return Result.success(service.decide(actor(principal),id,request));}
    @com.ruanzhu.doorhandle.contracts.agent.FileDelivery(domain="QUALITY_REPORT",resource="arg1",scope="ENTERPRISE")
    @PostMapping("/{id}/export") public ResponseEntity<byte[]> export(@AuthenticationPrincipal TenantPrincipal principal,@PathVariable String id,
            @RequestHeader(value="X-Report-Action",required=false) String header,@RequestParam(defaultValue="md")String format){guard(header);
        if("md".equals(format))return ResponseEntity.ok().contentType(new MediaType("text","markdown",StandardCharsets.UTF_8)).cacheControl(CacheControl.noStore())
                .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(id+".md").build().toString()).body(service.export(actor(principal),id).getBytes(StandardCharsets.UTF_8));
        var file=service.exportDocument(actor(principal),id,format);
        return ResponseEntity.ok().contentType(MediaType.parseMediaType(file.mediaType())).cacheControl(CacheControl.noStore())
                .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(id+"."+file.extension()).build().toString()).header("X-Content-Type-Options","nosniff").body(file.bytes());}
    private static Identity actor(TenantPrincipal p){if(p==null)throw new SecurityException("请先登录");return new Identity(p.userId(),p.username(),false);}
    public ResponseEntity<byte[]> export(TenantPrincipal principal,String id,String header){return export(principal,id,header,"md");}
    private static void guard(String header){if(!"update".equals(header))throw new BusinessException(400,"缺少报告操作请求标记");}
}

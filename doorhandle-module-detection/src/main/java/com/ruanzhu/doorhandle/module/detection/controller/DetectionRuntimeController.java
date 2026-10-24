package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.contracts.security.QualityAssigneeDirectory;
import com.ruanzhu.doorhandle.module.detection.service.DetectionExecutionStatusService;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import java.util.List;

@RestController
@RequestMapping("/api/detection")
@Validated
public class DetectionRuntimeController {
    private final DetectionExecutionStatusService execution;
    private final QualityAssigneeDirectory assignees;
    public DetectionRuntimeController(DetectionExecutionStatusService execution, QualityAssigneeDirectory assignees) {
        this.execution=execution; this.assignees=assignees;
    }
    @GetMapping("/runtime")
    public org.springframework.http.ResponseEntity<Result<DetectionExecutionStatusService.Status>> runtime() {
        return org.springframework.http.ResponseEntity.ok().cacheControl(org.springframework.http.CacheControl.noStore())
                .body(Result.success(execution.current()));
    }
    @GetMapping("/quality-assignees")
    @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public org.springframework.http.ResponseEntity<Result<List<QualityAssigneeDirectory.Option>>> assignees(@RequestParam(defaultValue="") @Size(max=50) String keyword) {
        return org.springframework.http.ResponseEntity.ok().cacheControl(org.springframework.http.CacheControl.noStore()).body(Result.success(assignees.search(keyword)));
    }
}

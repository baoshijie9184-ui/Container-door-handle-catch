package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionApplicationHistory;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDecisionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDispatchRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitImageBindRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import com.ruanzhu.doorhandle.module.detection.service.DetectionWorkUnitService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.access.prepost.PreAuthorize;
import java.util.List;

@RestController
@RequestMapping("/api/detection/supervisor/work-units")
@RequiredArgsConstructor
public class DetectionWorkUnitSupervisorController {
    private final DetectionWorkUnitService service;

    @GetMapping("/pending") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<List<DetectionWorkUnit>> pending() { return Result.success(service.listActive()); }

    @GetMapping("/history")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<DetectionApplicationHistory.Page> history(@RequestParam(defaultValue = "1") int page,
                                                            @RequestParam(defaultValue = "20") int size,
                                                            @RequestParam(required = false) String keyword,
                                                            @RequestParam(required = false) String taskId) {
        return Result.success(service.applicationHistory(page, size, keyword, taskId));
    }

    @PostMapping("/{workUnitId}/reject") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<DetectionWorkUnit> reject(@PathVariable String workUnitId,
                                            @Valid @RequestBody DetectionWorkUnitDecisionRequest request) {
        return Result.success(service.reject(workUnitId, request));
    }

    @PostMapping("/{workUnitId}/dispatch") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<DetectionWorkUnit> dispatch(@PathVariable String workUnitId, @Valid @RequestBody DetectionWorkUnitDispatchRequest request) {
        return Result.success(service.dispatch(workUnitId, request, "supervisor"));
    }

    @PostMapping("/{workUnitId}/recall") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<DetectionWorkUnit> recall(@PathVariable String workUnitId, @RequestParam Integer expectedVersion) {
        return Result.success(service.recall(workUnitId, expectedVersion, "supervisor"));
    }

    @PostMapping("/{workUnitId}/images") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<List<DetectionWorkUnitImage>> bindImages(@PathVariable String workUnitId, @Valid @RequestBody DetectionWorkUnitImageBindRequest request) {
        return Result.success(service.bindImages(workUnitId, request, "supervisor"));
    }

    @GetMapping("/{workUnitId}/images") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<List<DetectionWorkUnitImage>> images(@PathVariable String workUnitId) {
        return Result.success(service.listImages(workUnitId));
    }
}

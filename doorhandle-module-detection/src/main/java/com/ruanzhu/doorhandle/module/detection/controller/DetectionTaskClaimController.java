package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskClaimService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/detection/tasks")
@ConditionalOnProperty(prefix="collaboration.mutations",name="enabled",havingValue="true")
public class DetectionTaskClaimController {
    private final DetectionTaskClaimService service;
    public DetectionTaskClaimController(DetectionTaskClaimService service){this.service=service;}
    @PostMapping("/{taskId}/claim")
    public Result<DetectionTaskProgressResponse> claim(@PathVariable String taskId,@RequestBody DetectionTaskClaimService.Claim command){return Result.success(service.claim(taskId,command));}
}

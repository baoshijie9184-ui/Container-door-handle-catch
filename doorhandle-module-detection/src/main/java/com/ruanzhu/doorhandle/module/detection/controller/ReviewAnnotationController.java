package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.service.ReviewAnnotations;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/detection/tasks/{id}/annotations")
public class ReviewAnnotationController {
    private final ReviewAnnotations annotations;

    @GetMapping
    public Result<ReviewAnnotations.View> get(@PathVariable String id, @RequestParam String sourceKey,
            @RequestParam(defaultValue="false") boolean withModel) {
        return Result.success(annotations.get(id,sourceKey,withModel));
    }

    @PostMapping
    public Result<ReviewAnnotations.View> save(@PathVariable String id,@RequestBody ReviewAnnotations.Save input) {
        return Result.success(annotations.save(id,input));
    }
}

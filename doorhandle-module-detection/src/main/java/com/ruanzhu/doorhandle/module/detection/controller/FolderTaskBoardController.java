package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.service.FolderTaskBoard;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@Validated
@RequestMapping("/api/detection/board")
@RequiredArgsConstructor
public class FolderTaskBoardController {
    private final FolderTaskBoard board;
    @GetMapping
    public Result<Map<String,Object>> list(@RequestParam(required=false) String phase,@RequestParam(required=false) String keyword,
            @RequestParam(defaultValue="false") boolean inbox,@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size){
        return Result.success(board.list(phase,keyword,inbox,page,size));
    }
    @GetMapping("/folders")
    public Result<FolderTaskBoard.Folder> folders(@RequestParam(required=false) String prefix,@RequestParam(required=false) String marker) {
        return Result.success(board.folders(prefix,marker));
    }
    @PostMapping
    public Result<String> create(@RequestBody FolderTaskBoard.Create request){return Result.success(board.create(request));}
    @PostMapping("/{id}/assign")
    public Result<Void> assign(@PathVariable String id,@RequestBody FolderTaskBoard.Assign request){board.assign(id,request);return Result.success(null);}
    @PostMapping("/{id}/start")
    public Result<Void> start(@PathVariable String id,@RequestParam @Min(0) int version){board.start(id,version);return Result.success(null);}
}

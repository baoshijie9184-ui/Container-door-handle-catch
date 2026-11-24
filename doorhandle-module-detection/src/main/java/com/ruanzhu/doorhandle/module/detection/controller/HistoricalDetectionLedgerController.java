package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assigned;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assignments;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Page;
import com.ruanzhu.doorhandle.module.detection.service.HistoricalDetectionLedgerService;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Validated
@RequestMapping("/api/detection/historical-ledger")
public class HistoricalDetectionLedgerController {
    private final HistoricalDetectionLedgerService ledger;

    public HistoricalDetectionLedgerController(HistoricalDetectionLedgerService ledger) {
        this.ledger = ledger;
    }

    @GetMapping
    public Result<Page> list(@RequestParam(defaultValue = "mine") String scope,
                             @RequestParam(defaultValue = "1") @Min(1) int page,
                             @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size) {
        return Result.success(ledger.list(scope, page, size));
    }

    @PostMapping("/assignments")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Assigned> assign(@RequestBody Assignments request) {
        return Result.success(ledger.assign(request));
    }

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<Result<String>> businessError(BusinessException error) {
        return ResponseEntity.status(error.getCode()).body(Result.error(error.getCode(), error.getMessage()));
    }
}

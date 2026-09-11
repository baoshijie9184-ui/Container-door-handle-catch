package com.ruanzhu.doorhandle.module.app.service;

import org.springframework.web.multipart.MultipartFile;

public interface SpeechTranscriptionService {

    String transcribe(MultipartFile file);
}

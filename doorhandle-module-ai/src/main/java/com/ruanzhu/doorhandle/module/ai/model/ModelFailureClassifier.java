package com.ruanzhu.doorhandle.module.ai.model;

import io.agentscope.core.model.ModelHttpException;
import io.agentscope.core.model.ModelException;
import io.agentscope.core.model.transport.HttpTransportException;
import java.io.IOException;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Locale;
import java.util.concurrent.TimeoutException;
import com.openai.errors.OpenAIServiceException;
import com.openai.errors.OpenAIIoException;

/** 只在内存中识别上游错误，不记录或对外返回错误正文。 */
final class ModelFailureClassifier {
    enum Failure { TRANSIENT, QUOTA, AUTH, OTHER }

    static Failure classify(Throwable error) {
        Integer status = status(error);
        var seen = Collections.newSetFromMap(new IdentityHashMap<Throwable, Boolean>());
        boolean transport = false;
        for (Throwable cause = error; cause != null && seen.add(cause); cause = cause.getCause()) {
            if ((status != null && status >= 400 && status < 600 || cause instanceof ModelException)
                    && quotaText(cause.getMessage())) return Failure.QUOTA;
            if (cause instanceof HttpTransportException http && quotaText(http.getResponseBody())) return Failure.QUOTA;
            if (cause instanceof OpenAIServiceException http
                    && (quotaText(http.code().orElse(null)) || quotaText(http.type().orElse(null))
                    || quotaText(http.body().toString()))) return Failure.QUOTA;
            transport |= cause instanceof TimeoutException || cause instanceof IOException
                    || cause instanceof OpenAIIoException || cause instanceof EmptyResponseException
                    || cause instanceof java.util.concurrent.RejectedExecutionException;
        }
        if (status != null) {
            if (status == 402) return Failure.QUOTA;
            if (status == 401 || status == 403) return Failure.AUTH;
            if (status == 408 || status == 409 || status == 429 || status >= 500 && status < 600) return Failure.TRANSIENT;
            return Failure.OTHER;
        }
        return transport ? Failure.TRANSIENT : Failure.OTHER;
    }

    static Integer status(Throwable error) {
        var seen = Collections.newSetFromMap(new IdentityHashMap<Throwable, Boolean>());
        for (Throwable cause = error; cause != null && seen.add(cause); cause = cause.getCause()) {
            Integer status = cause instanceof ModelHttpException http ? http.getStatusCode()
                    : cause instanceof HttpTransportException http ? http.getStatusCode()
                    : cause instanceof OpenAIServiceException http ? http.statusCode() : null;
            if (status != null) return status;
        }
        return null;
    }

    static String reason(Throwable error) {
        var failure = classify(error);
        if (failure == Failure.QUOTA || failure == Failure.AUTH) return failure.name();
        var seen = Collections.newSetFromMap(new IdentityHashMap<Throwable, Boolean>());
        for (Throwable cause = error; cause != null && seen.add(cause); cause = cause.getCause()) {
            if (cause instanceof TimeoutException) return "TIMEOUT";
            if (cause instanceof java.util.concurrent.RejectedExecutionException) return "CAPACITY";
            if (cause instanceof EmptyResponseException) return "EMPTY_RESPONSE";
        }
        return failure.name();
    }

    private static boolean quotaText(String text) {
        if (text == null) return false;
        String value = text.toLowerCase(Locale.ROOT);
        return value.contains("insufficient_quota") || value.contains("insufficient_balance")
                || value.contains("allocationquota.freetieronly")
                || value.contains("insufficient balance") || value.contains("insufficient funds")
                || value.contains("quota_exceeded") || value.contains("quota exceeded")
                || value.contains("billing_hard_limit_reached") || value.contains("credit balance is too low")
                || value.contains("arrearage") || value.contains("余额不足") || value.contains("额度不足")
                || value.contains("欠费");
    }

    static final class EmptyResponseException extends RuntimeException {
        EmptyResponseException() { super("模型未返回有效内容"); }
    }
}

package com.ruanzhu.doorhandle.framework.semantic;

/** Fixed error codes deliberately omit content, tokens and provider response bodies. */
public final class SemanticUnavailableException extends RuntimeException {
    public SemanticUnavailableException(String code) { super(code); }
}

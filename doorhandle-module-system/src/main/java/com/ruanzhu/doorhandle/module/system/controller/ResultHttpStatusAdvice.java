package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.Result;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice;

/** Collaboration clients need transport errors to match the existing Result contract. */
@RestControllerAdvice
@ConditionalOnProperty(prefix="collaboration.mutations",name="enabled",havingValue="true")
public class ResultHttpStatusAdvice implements ResponseBodyAdvice<Object> {
    @Override public boolean supports(MethodParameter returnType,Class<? extends HttpMessageConverter<?>> converterType){return true;}
    @Override public Object beforeBodyWrite(Object body,MethodParameter returnType,MediaType contentType,
            Class<? extends HttpMessageConverter<?>> converterType,ServerHttpRequest request,ServerHttpResponse response){
        if(body instanceof Result<?> result&&result.getCode()!=null&&result.getCode()>=400&&result.getCode()<=599){
            response.setStatusCode(HttpStatusCode.valueOf(result.getCode()));response.getHeaders().setCacheControl("no-store");
        }
        return body;
    }
}

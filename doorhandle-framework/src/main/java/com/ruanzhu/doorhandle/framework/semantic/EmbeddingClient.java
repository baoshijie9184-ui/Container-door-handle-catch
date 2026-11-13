package com.ruanzhu.doorhandle.framework.semantic;

import java.util.List;

/** Embedding capability shared by content owners, without exposing a provider credential. */
public interface EmbeddingClient {
    record RequestContext(String purpose, String account) { }
    List<List<Float>> embed(List<String> texts, RequestContext context);
}

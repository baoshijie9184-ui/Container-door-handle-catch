package com.ruanzhu.doorhandle.contracts.agent;

/** Only authenticated, encrypted configuration crosses the private service bridge. */
public interface MemoryModelConfigApi {
    void prepare(long revision,String envelope);
    void apply(long revision);
    long appliedRevision();
    void revokeCredential(String fingerprint);
}

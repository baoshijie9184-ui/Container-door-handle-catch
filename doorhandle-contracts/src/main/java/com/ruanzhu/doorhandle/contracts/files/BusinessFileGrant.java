package com.ruanzhu.doorhandle.contracts.files;

/** Trusted owner-issued metadata. A file ID identifies a mapped location, not a content checksum. */
public record BusinessFileGrant(String resourceId,String fileId,Long version) {
    public BusinessFileGrant {
        if(resourceId==null || !resourceId.matches("[A-Za-z0-9_:./-]{1,160}")
                || fileId==null || !fileId.matches("[a-f0-9]{64}") || version!=null && version<0)
            throw new IllegalArgumentException("业务文件授权元数据无效");
    }
}

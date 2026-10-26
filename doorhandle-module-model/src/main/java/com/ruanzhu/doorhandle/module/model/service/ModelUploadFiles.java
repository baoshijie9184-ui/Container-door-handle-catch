package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.multipart.MultipartFile;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;

/** Private immutable managed uploads. Failed or uncertain registration never deletes their bytes. */
@Service
public class ModelUploadFiles {
    public record Prepared(String fileId,String requestId,long actorUserId,Path path,String sha256,long size) {
        @Override public String toString() { return "PreparedModelFile["+fileId+"]"; }
    }
    private final ObjectProvider<ModelFileJournal> journals;
    private final ModelMutationIdentity identity;
    private final Path root;
    private final long maxBytes;
    public ModelUploadFiles(ObjectProvider<ModelFileJournal> journals, ModelMutationIdentity identity,
            @Value("${model.upload-dir:${user.dir}/uploads/models}") String root,
            @Value("${model.max-upload-bytes:209715200}") long maxBytes) {
        this.journals=journals;this.identity=identity;this.root=Path.of(root).toAbsolutePath().normalize();this.maxBytes=maxBytes;
        if(maxBytes<1) throw new IllegalArgumentException("模型上传限制无效");
    }
    public Prepared write(MultipartFile upload) {
        if(TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("模型上传不能在数据库事务中执行");
        var actor=identity.supervisor();
        String request=identity.requestId(),fileId=UUID.randomUUID().toString();
        Path target=root.resolve(fileId+".onnx");
        if(target.toString().length()>255) throw new BusinessException("模型存储目录过长，未开始写入");
        var journal=journals.getIfAvailable();
        try {
            checkParents(root);
            Files.createDirectories(root);
            checkParents(root);
            if(journal!=null) journal.reserve(fileId,request,target.toString());
            var digest=MessageDigest.getInstance("SHA-256");long count=0;
            java.util.Set<OpenOption> options=java.util.Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
            java.nio.file.attribute.FileAttribute<?>[] attributes=Files.getFileAttributeView(root,java.nio.file.attribute.PosixFileAttributeView.class)==null
                    ?new java.nio.file.attribute.FileAttribute<?>[0]
                    :new java.nio.file.attribute.FileAttribute<?>[]{java.nio.file.attribute.PosixFilePermissions.asFileAttribute(
                            java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"))};
            try(InputStream input=upload.getInputStream(); FileChannel output=FileChannel.open(target,options,attributes)) {
                byte[] buffer=new byte[65536];int read;
                while((read=input.read(buffer))!=-1) {
                    if(read==0) continue;
                    if(read>maxBytes-count) throw new BusinessException("模型文件超过上传大小限制");
                    digest.update(buffer,0,read);count+=read;
                    var bytes=ByteBuffer.wrap(buffer,0,read);
                    while(bytes.hasRemaining()) output.write(bytes);
                }
                if(count<1 || count!=upload.getSize()) throw new BusinessException("模型文件长度不一致，保留上传记录待核对");
                output.force(true);
            }
            var result=new Prepared(fileId,request,actor.userId(),target,HexFormat.of().formatHex(digest.digest()),count);
            if(journal!=null) journal.ready(result);
            return result;
        } catch(IOException failure) {
            // Even an error returned from commit can mean SQL committed. Never delete on uncertainty.
            throw new BusinessException("保存模型文件未完成，请使用请求编号核对，不要自动重试");
        } catch(java.security.NoSuchAlgorithmException failure) { throw new IllegalStateException(failure); }
    }
    public void verify(Prepared file) {
        var actor=identity.supervisor();
        if(actor.userId()!=file.actorUserId()) throw new SecurityException("模型上传账号已变化");
        if(TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("模型摘要核对不得占用业务事务");
        if(!file.path().equals(root.resolve(file.fileId()+".onnx"))) throw new SecurityException("模型上传位置无效");
        try {
            checkParents(file.path());
            if(!Files.isRegularFile(file.path(),LinkOption.NOFOLLOW_LINKS) || Files.size(file.path())!=file.size()) throw new IOException("changed");
            var digest=MessageDigest.getInstance("SHA-256");long count=0;
            try(InputStream input=Files.newInputStream(file.path(),LinkOption.NOFOLLOW_LINKS)) {
                byte[] buffer=new byte[65536];int read;
                while((read=input.read(buffer))!=-1) {
                    if(read>file.size()-count) throw new IOException("changed");
                    if(read>0) { count+=read;digest.update(buffer,0,read); }
                }
            }
            if(count!=file.size() || !file.sha256().equals(HexFormat.of().formatHex(digest.digest()))) throw new IOException("changed");
        } catch(IOException failure) { throw new BusinessException("模型文件已变化，未登记，保留文件待核对"); }
        catch(java.security.NoSuchAlgorithmException failure) { throw new IllegalStateException(failure); }
    }
    /** Old metadata forms cannot claim another managed upload or detach its registered evidence. */
    public void metadataPath(String incoming,String existing) {
        identity.supervisor();
        if(java.util.Objects.equals(incoming,existing) || incoming==null) return;
        try {
            Path next=Path.of(incoming).toAbsolutePath().normalize();
            Path previous=existing==null?null:Path.of(existing).toAbsolutePath().normalize();
            if(next.startsWith(root) || (previous!=null && previous.startsWith(root)))
                throw new BusinessException("托管模型文件只能通过上传登记，不能在元数据中替换路径");
        } catch(InvalidPathException failure) { throw new BusinessException("模型路径无效"); }
    }
    private static void checkParents(Path path) throws IOException {
        for(Path cursor=path;cursor!=null;cursor=cursor.getParent()) {
            if(Files.isSymbolicLink(cursor)) throw new IOException("symbolic link");
        }
    }
}

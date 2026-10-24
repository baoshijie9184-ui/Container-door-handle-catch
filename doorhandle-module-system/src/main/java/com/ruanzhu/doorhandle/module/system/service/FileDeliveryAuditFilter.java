package com.ruanzhu.doorhandle.module.system.service;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.*;

/** Counts successful servlet writes without retaining body contents or buffering the entire file. */
@Component @Order(Ordered.HIGHEST_PRECEDENCE+25)
@ConditionalOnProperty(prefix="operations.audit",name="file-delivery-enabled",havingValue="true")
public class FileDeliveryAuditFilter extends OncePerRequestFilter {
    private final FileDeliveryAuditService deliveries;
    public FileDeliveryAuditFilter(FileDeliveryAuditService deliveries){this.deliveries=deliveries;}
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException{
        var counted=new Counted(request,response);boolean failed=false;
        try{chain.doFilter(request,counted);}catch(ServletException|IOException|RuntimeException failure){failed=true;throw failure;}
        finally{
            var ticket=counted.ticket();if(ticket!=null&&!ticket.redirect()){
                try{counted.flushWriter();}catch(RuntimeException failure){failed=true;}
                boolean unknown=request.isAsyncStarted()||counted.discarded;
                Long expected=(Long)request.getAttribute(FileDeliveryAuditAspect.TICKET+".length");
                String declared=counted.getHeader("Content-Length");
                if(counted.getStatus()==206)expected=null;
                if(ticket.headersOnly())expected=0L;
                else if(declared!=null)try{expected=Long.parseLong(declared);}catch(NumberFormatException invalid){unknown=true;}
                boolean interrupted=failed||counted.failed||expected!=null&&expected!=counted.count;
                try{deliveries.finish(ticket,counted.discarded?0:counted.count,counted.getStatus(),interrupted,unknown);}
                catch(RuntimeException unavailable){logger.warn("File response ended without a durable terminal receipt; original authorization remains for reconciliation");}
            }
        }
    }
    private final class Counted extends HttpServletResponseWrapper {
        private final HttpServletRequest request;private ServletOutputStream output;private PrintWriter writer;
        private long count;private boolean started,failed,discarded;
        Counted(HttpServletRequest request,HttpServletResponse response){super(response);this.request=request;}
        FileDeliveryAuditService.Ticket ticket(){Object value=request.getAttribute(FileDeliveryAuditAspect.TICKET);return value instanceof FileDeliveryAuditService.Ticket ticket?ticket:null;}
        private void before()throws IOException{var ticket=ticket();if(ticket!=null&&!ticket.redirect()&&!ticket.headersOnly()&&!started&&!discarded){try{deliveries.started(ticket);started=true;}catch(RuntimeException unavailable){failed=true;throw new IOException("Required file delivery audit unavailable");}}}
        @Override public ServletOutputStream getOutputStream()throws IOException{
            if(writer!=null)throw new IllegalStateException("Writer already selected");return stream();
        }
        private ServletOutputStream stream()throws IOException{
            if(output==null){var target=super.getOutputStream();output=new ServletOutputStream(){
                @Override public boolean isReady(){return target.isReady();}
                @Override public void setWriteListener(WriteListener listener){target.setWriteListener(listener);}
                @Override public void write(int value)throws IOException{before();try{target.write(value);if(ticket()!=null&&!ticket().headersOnly()&&!discarded)count++;}catch(IOException error){failed=true;throw error;}}
                @Override public void write(byte[] value,int offset,int length)throws IOException{if(length==0)return;before();try{target.write(value,offset,length);if(ticket()!=null&&!ticket().headersOnly()&&!discarded)count+=length;}catch(IOException error){failed=true;throw error;}}
                @Override public void flush()throws IOException{try{target.flush();}catch(IOException error){failed=true;throw error;}}
                @Override public void close()throws IOException{try{target.close();}catch(IOException error){failed=true;throw error;}}
            };}return output;
        }
        @Override public PrintWriter getWriter()throws IOException{if(output!=null&&writer==null)throw new IllegalStateException("Output stream already selected");if(writer==null)writer=new PrintWriter(new OutputStreamWriter(stream(),getCharacterEncoding()));return writer;}
        void flushWriter(){if(writer!=null){writer.flush();if(writer.checkError())failed=true;}}
        @Override public void resetBuffer(){super.resetBuffer();if(ticket()!=null){discarded=true;count=0;}}
        @Override public void reset(){super.reset();if(ticket()!=null){discarded=true;count=0;}}
    }
}

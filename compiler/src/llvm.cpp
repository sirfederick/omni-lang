#include "omni.hpp"
namespace omni  {
    namespace  {
        // The profile being lowered (null for hosted output). lt() is a free function, so the ISA contract of the freestanding
        // x86-64 profile is carried here: in `gpr` mode a floating-point type has no lowering (CP-10, FPU_SSE_STATE_CANDIDATE.md).
        const TargetProfile* gLoweringProfile=nullptr;
        std::string lt(Type t)  {
            if(t.kind==Type::Bool)return "i1";
            if(t.kind==Type::Char)return "i32";
            if(isInteger(t))return "i"+std::to_string(integerWidth(t));
            if((t.kind==Type::F32||t.kind==Type::F64)&&gLoweringProfile&&gLoweringProfile->name=="baremetal-x86_64"&&gLoweringProfile->isa!="sse2")
                fail("E_TARGET_PROFILE","f32/f64 requieren --target-isa sse2 en el perfil baremetal-x86_64 (la imagen solo usa registros de proposito general)");
            if(t.kind==Type::F32)return "float";
            if(t.kind==Type::F64)return "double";
            if(t.kind==Type::Text||t.kind==Type::Bytes||t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::BorrowMut)return "i64";
            // A85's initial deterministic scheduler has no suspension point in a
            // spawned scalar expression. A Future<T> stores its completed T; the
            // checker alone controls its linear join capability.
            if(t.kind==Type::Future)return lt(t.parts.at(0));
            if(t.kind==Type::Stream)return "i64";
            if(t.kind==Type::Record)return "%omni.type."+t.key;
            if(t.kind==Type::Enum)return "%omni.enum."+t.key;
            if(t.kind==Type::Result)return "{ i1, "+lt(t.parts[0])+", "+lt(t.parts[1])+" }";
            if(t.kind==Type::Option)return "{ i1, "+lt(t.parts[0])+" }";
            if(t.kind==Type::Tuple){ std::string r="{ "; for(size_t i=0;i<t.parts.size();++i){if(i)r+=", ";r+=lt(t.parts[i]);} return r+" }"; }
            if(t.kind==Type::Array)return "["+std::to_string(t.extent)+" x "+lt(t.parts.at(0))+"]";
            if(t.kind==Type::View)return "{ ptr, i32 }";
            if(t.kind==Type::Range)return "{ i32, i32, i1 }";
            fail("E_INTERNAL","tipo sin lowering");
        }
        class LLVM  {
            const Program& p;
            std::ostringstream out,globals;
            // Declarations of runtime entry points that only some programs call. They are appended at the end of the module, and only when used, so
            // that a program that does not use the feature produces exactly the bytes the previous compiler produced.
            std::set<std::string> lateDecls;
            std::string lateText() const { std::string text; for(const auto& declaration:lateDecls)text+=declaration+"\n"; return text; }
            int temp=0,label=0,strings=0;
            std::string current;
            struct LoopTarget { std::string continueTarget,breakTarget; size_t cleanupDepth=0; };
            std::vector<LoopTarget> loopTargets;
            // Each lexical source block owns the bindings it introduced.  This
            // is a checked lowering plan, not an implicit runtime authority.
            std::vector<std::vector<int>> cleanupScopes;
            const Function* fn=nullptr;
            const TargetProfile* prof=nullptr;
            bool svcFn=false;
            // CP-10: in an `sse2` image floating-point arithmetic honours the dynamic FP environment (MXCSR rounding): it is lowered to
            // LLVM constrained intrinsics (round.dynamic, fpexcept.strict) inside `strictfp` functions, so the optimizer cannot merge, hoist
            // or reorder it across cpu.write_mxcsr / cpu.fxrstor. Hosted output keeps plain fadd/fmul/... (FPU_SSE_STATE_CANDIDATE.md).
            bool sse2() const { return prof&&prof->name=="baremetal-x86_64"&&prof->isa=="sse2"; }
            std::string constrainedBinary(const std::string& op,const std::string& ty,const std::string& a,const std::string& b) {
                auto r=reg();
                emit(r+" = call "+ty+" @llvm.experimental.constrained."+op+"."+(ty=="float"?"f32":"f64")+"("+ty+" "+a+", "+ty+" "+b+", metadata !\"round.dynamic\", metadata !\"fpexcept.strict\") strictfp");
                return r;
            }
            std::string reg()  {
                return "%t"+std::to_string(temp++);
            }
            std::string lab()  {
                return "b"+std::to_string(label++);
            }
            void emit(const std::string& s)  {
                out<<"  "<<s<<"\n";
            }
            // Fixed-size temporaries are allocated once per call frame, in the
            // entry block. A use-site alloca inside a loop body is dynamic stack
            // growth that LLVM never releases before function exit.
            std::vector<std::string> hoisted;
            void hoist(const std::string& r,const std::string& ty)  {
                hoisted.push_back("  "+r+" = alloca "+ty+"\n");
            }
            void mark(const std::string& l)  {
                out<<l<<":\n";
                current=l;
            }
            void tick()  {
                if(svcFn)return;
                emit("call void @omni_tick()");
            }
            const RecordDef& recordFor(const Type& t) const {
                for(const auto& record:p.records)if(record.key==t.key)return record;
                fail("E_INTERNAL","record sin definicion durante cleanup LLVM");
            }
            std::vector<int> scopeBindings(const std::vector<Stmt>& body,const std::vector<int>& extra={}) const {
                std::vector<int> bindings=extra;
                for(const auto& statement:body) {
                    if(statement.kind==Stmt::Let||statement.kind==Stmt::Var)bindings.push_back(statement.binding);
                    else if(statement.kind==Stmt::Destructure)
                        bindings.insert(bindings.end(),statement.bindings.begin(),statement.bindings.end());
                }
                return bindings;
            }
            void cleanupValue(const Type& type,const std::string& ptr) {
                if(type.kind==Type::Resource) {
                    if(type.name!="Buffer")return;   // nominal resource: no automatic cleanup (checker proves it was consumed)
                    auto handle=reg(),live=reg(),release=lab(),done=lab();
                    emit(handle+" = load i64, ptr "+ptr);
                    emit(live+" = icmp ne i64 "+handle+", 0");
                    emit("br i1 "+live+", label %"+release+", label %"+done);
                    mark(release);
                    auto result=reg();
                    emit(result+" = call i32 @omni_buffer_release(i64 "+handle+")");
                    emit("store i64 0, ptr "+ptr);
                    emit("br label %"+done);
                    mark(done);
                    return;
                }
                if(type.kind==Type::Tuple){
                    for(size_t i=type.parts.size();i>0;--i){
                        const auto index=i-1;auto field=reg();
                        emit(field+" = getelementptr "+lt(type)+", ptr "+ptr+", i32 0, i32 "+std::to_string(index));
                        cleanupValue(type.parts[index],field);
                    }
                    return;
                }
                if(type.kind==Type::Array){
                    if(!typeContainsResource(p,type,fn->module))return;   // plain arrays (up to 65535 elements) own nothing
                    for(uint32_t i=type.extent;i>0;--i){
                        const auto index=i-1;auto field=reg();
                        emit(field+" = getelementptr "+lt(type)+", ptr "+ptr+", i32 0, i32 "+std::to_string(index));
                        cleanupValue(type.parts.at(0),field);
                    }
                    return;
                }
                if(type.kind!=Type::Record)return;
                const auto& record=recordFor(type);
                for(size_t i=record.fields.size();i>0;--i) {
                    const auto index=i-1;
                    auto field=reg();
                    emit(field+" = getelementptr "+lt(type)+", ptr "+ptr+", i32 0, i32 "+std::to_string(index));
                    cleanupValue(record.fields[index].type,field);
                }
            }
            void cleanupFrom(size_t depth) {
                for(size_t scope=cleanupScopes.size();scope>depth;--scope) {
                    const auto& bindings=cleanupScopes[scope-1];
                    for(auto binding=bindings.rbegin();binding!=bindings.rend();++binding)
                        if(*binding>=0)cleanupValue(fn->locals.at(static_cast<size_t>(*binding)),"%v"+std::to_string(*binding));
                }
            }
            void consumePlace(const Expr& e) {
                if(e.placeRoot<0)fail("E_INTERNAL","move without a checked Place in LLVM");
                std::string ptr="%v"+std::to_string(e.placeRoot);
                Type currentType=fn->locals.at(static_cast<size_t>(e.placeRoot));
                for(const auto projection:e.placePath) {
                    if(projection<0)fail("E_INTERNAL","negative LLVM Place projection");
                    const auto index=static_cast<size_t>(projection);
                    Type next;
                    if(currentType.kind==Type::Record){
                        const auto& record=recordFor(currentType);
                        if(index>=record.fields.size())fail("E_INTERNAL","invalid record LLVM Place projection");
                        next=record.fields[index].type;
                    } else if(currentType.kind==Type::Tuple){
                        if(index>=currentType.parts.size())fail("E_INTERNAL","invalid Tuple LLVM Place projection");
                        next=currentType.parts[index];
                    } else if(currentType.kind==Type::Array){
                        if(index>=currentType.extent)fail("E_INTERNAL","invalid Array LLVM Place projection");
                        next=currentType.parts.at(0);
                    } else fail("E_INTERNAL","non-product projection in LLVM Place");
                    auto field=reg();
                    emit(field+" = getelementptr "+lt(currentType)+", ptr "+ptr+", i32 0, i32 "+std::to_string(projection));
                    ptr=field;
                    currentType=std::move(next);
                }
                if(currentType.kind!=Type::Resource)fail("E_INTERNAL","move Place is not a Resource in LLVM");
                emit("store i64 0, ptr "+ptr);
            }
            std::string expr(const Expr& e)  {
                tick();
                switch(e.kind)  {
                    case Expr::Number:
                        if(e.type.kind==Type::F32)return "bitcast (i32 "+std::to_string(static_cast<uint32_t>(e.value))+" to float)";
                        if(e.type.kind==Type::F64)return "bitcast (i64 "+std::to_string(e.value)+" to double)";
                        return std::to_string(e.value);
                    case Expr::Boolean:return e.value?"true":"false";
                    case Expr::Text: {
                        auto name="@.dyntext."+std::to_string(strings++);
                        globals<<name<<" = private unnamed_addr constant ["<<e.text.size()<<" x i8] c\"";
                        for(char raw:e.text){ const auto c=static_cast<unsigned char>(raw); globals<<"\\"<<std::uppercase<<std::hex<<std::setw(2)<<std::setfill('0')<<static_cast<unsigned>(c); }
                        globals<<std::dec<<"\"\n";
                        auto r=reg();
                        emit(r+" = call i64 @omni_text_new(ptr "+name+", i32 "+std::to_string(e.text.size())+")");
                        return r;
                    }
                    case Expr::Ref:  {
                        auto r=reg();
                        emit(r+" = load "+lt(e.type)+", ptr %v"+std::to_string(e.binding));
                        return r;
                    }
                    case Expr::Call:  {
                        std::vector<std::string> av;
                        for(auto &a:e.args) av.push_back((a.resolved.rfind("@tls:",0)==0||a.resolved.rfind("@field:",0)==0)?std::string():expr(a));
                        if(e.resolved=="@builtin:range.exclusive"||e.resolved=="@builtin:range.inclusive") {
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i32 "+av[0]+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+av[1]+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i1 "+std::string(e.resolved=="@builtin:range.inclusive"?"true":"false")+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:tuple.make"||e.resolved=="@builtin:array.make") {
                            std::string acc="zeroinitializer";
                            for(size_t i=0;i<e.args.size();++i){ auto r=reg(); emit(r+" = insertvalue "+lt(e.type)+" "+acc+", "+lt(e.args[i].type)+" "+av[i]+", "+std::to_string(i)); acc=r; }
                            return acc;
                        }
                        if(e.resolved=="@builtin:tuple.get"||e.resolved=="@builtin:array.place") { auto r=reg(); emit(r+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", "+std::to_string(e.binding)); return r; }
                        if(e.resolved=="@builtin:array.fill") {
                            std::string acc="zeroinitializer";
                            for(int i=0;i<e.binding;++i){ auto r=reg(); emit(r+" = insertvalue "+lt(e.type)+" "+acc+", "+lt(e.args[0].type)+" "+av[0]+", "+std::to_string(i)); acc=r; }
                            return acc;
                        }
                        if(e.resolved=="@builtin:array.len") return std::to_string(e.binding);
                        if(e.resolved=="@builtin:array.get"||e.resolved=="@builtin:array.with") {
                            auto arrTy=lt(e.args[0].type), elemTy=lt(e.args[0].type.parts.at(0));
                            auto ok=reg(); emit(ok+" = icmp ult i32 "+av[1]+", "+std::to_string(e.binding));
                            auto good=lab(),bad=lab(),done=lab(); emit("br i1 "+ok+", label %"+good+", label %"+bad); mark(bad); emit("call void @omni_trap_bounds()"); emit("unreachable"); mark(good);
                            auto slot=reg(); hoist(slot,arrTy); emit("store "+arrTy+" "+av[0]+", ptr "+slot);
                            auto ptr=reg(); emit(ptr+" = getelementptr "+arrTy+", ptr "+slot+", i32 0, i32 "+av[1]);
                            if(e.resolved=="@builtin:array.get") { auto val=reg(); emit(val+" = load "+elemTy+", ptr "+ptr); emit("br label %"+done); mark(done); return val; }
                            emit("store "+elemTy+" "+av[2]+", ptr "+ptr); auto val=reg(); emit(val+" = load "+arrTy+", ptr "+slot); emit("br label %"+done); mark(done); return val;
                        }
                        if(e.resolved=="@builtin:view.make") {
                            auto arrTy=lt(e.args[0].type), elemTy=lt(e.args[0].type.parts.at(0));
                            auto slot=reg(); hoist(slot,arrTy); emit("store "+arrTy+" "+av[0]+", ptr "+slot);
                            auto base=reg(); emit(base+" = getelementptr "+arrTy+", ptr "+slot+", i32 0, i32 0");
                            auto r0=reg(),r1=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, ptr "+base+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+std::to_string(e.binding)+", 1"); return r1;
                        }
                        if(e.resolved=="@builtin:view.sub") {
                            auto elemTy=lt(e.type.parts.at(0)); auto base=reg(),baseLen=reg();
                            emit(base+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 0"); emit(baseLen+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 1");
                            auto offOk=reg(); emit(offOk+" = icmp ule i32 "+av[1]+", "+baseLen); auto rem=reg(); emit(rem+" = sub i32 "+baseLen+", "+av[1]);
                            auto lenOk=reg(); emit(lenOk+" = icmp ule i32 "+av[2]+", "+rem); auto ok=reg(); emit(ok+" = and i1 "+offOk+", "+lenOk);
                            auto good=lab(),bad=lab(),done=lab(); emit("br i1 "+ok+", label %"+good+", label %"+bad); mark(bad); emit("call void @omni_trap_bounds()"); emit("unreachable"); mark(good);
                            auto ptr=reg(); emit(ptr+" = getelementptr "+elemTy+", ptr "+base+", i32 "+av[1]); auto r0=reg(),r1=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, ptr "+ptr+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+av[2]+", 1"); emit("br label %"+done); mark(done); return r1;
                        }
                        if(e.resolved=="@builtin:view.len") { auto r=reg(); emit(r+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 1"); return r; }
                        if(e.resolved=="@builtin:view.get") {
                            auto elemTy=lt(e.args[0].type.parts.at(0)); auto base=reg(),len=reg(); emit(base+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 0"); emit(len+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 1");
                            auto ok=reg(); emit(ok+" = icmp ult i32 "+av[1]+", "+len); auto good=lab(),bad=lab(),done=lab(); emit("br i1 "+ok+", label %"+good+", label %"+bad); mark(bad); emit("call void @omni_trap_bounds()"); emit("unreachable"); mark(good);
                            auto ptr=reg(); emit(ptr+" = getelementptr "+elemTy+", ptr "+base+", i32 "+av[1]); auto val=reg(); emit(val+" = load "+elemTy+", ptr "+ptr); emit("br label %"+done); mark(done); return val;
                        }
                        if(e.resolved.rfind("@builtin:cast:",0)==0) {
                            auto src=e.args[0].type,dst=e.type;
                            if(isInteger(src)&&isInteger(dst)){
                                std::string wide=av[0];
                                if(integerWidth(src)<64){ auto x=reg(); emit(x+" = "+std::string(isSignedInteger(src)?"sext":"zext")+" "+lt(src)+" "+wide+" to i64"); wide=x; }
                                if(prof&&!isSignedInteger(src)&&!isSignedInteger(dst)) {
                                    // unsigned->unsigned: widening is lossless; narrowing is a checked range test.
                                    if(integerWidth(dst)==64)return wide;
                                    const uint64_t maxv=(UINT64_C(1)<<integerWidth(dst))-1;
                                    auto ok=reg(),good=lab(),bad=lab(); emit(ok+" = icmp ule i64 "+wide+", "+std::to_string(maxv)); emit("br i1 "+ok+", label %"+good+", label %"+bad);
                                    mark(bad); emit("call void @omni_fault(i32 4)"); emit("unreachable"); mark(good);
                                    auto r=reg(); emit(r+" = trunc i64 "+wide+" to "+lt(dst)); return r;
                                }
                                auto cv=reg(); emit(cv+" = call i64 @omni_cast_int(i64 "+wide+", i32 "+(isSignedInteger(src)?"1":"0")+", i32 "+std::to_string(integerWidth(src))+", i32 "+(isSignedInteger(dst)?"1":"0")+", i32 "+std::to_string(integerWidth(dst))+")");
                                if(integerWidth(dst)==64)return cv;
                                auto r=reg(); emit(r+" = trunc i64 "+cv+" to "+lt(dst)); return r;
                            }
                            if(isInteger(src)&&isFloat(dst)){
                                auto r=reg();
                                if(sse2()) {
                                    emit(r+" = call "+lt(dst)+" @llvm.experimental.constrained."+std::string(isSignedInteger(src)?"sitofp":"uitofp")+"."+(dst.kind==Type::F32?"f32":"f64")+".i"+std::to_string(integerWidth(src))+"("+lt(src)+" "+av[0]+", metadata !\"round.dynamic\", metadata !\"fpexcept.strict\") strictfp");
                                    return r;
                                }
                                emit(r+" = "+std::string(isSignedInteger(src)?"sitofp":"uitofp")+" "+lt(src)+" "+av[0]+" to "+lt(dst)); return r;
                            }
                            if(isFloat(src)&&isFloat(dst)){
                                if(src==dst)return av[0];
                                auto r=reg();
                                if(sse2()&&floatWidth(src)>floatWidth(dst)) {
                                    emit(r+" = call "+lt(dst)+" @llvm.experimental.constrained.fptrunc.f32.f64("+lt(src)+" "+av[0]+", metadata !\"round.dynamic\", metadata !\"fpexcept.strict\") strictfp");
                                    return r;
                                }
                                emit(r+" = "+std::string(floatWidth(src)<floatWidth(dst)?"fpext":"fptrunc")+" "+lt(src)+" "+av[0]+" to "+lt(dst)); return r;
                            }
                            if(isFloat(src)&&isInteger(dst)){
                                if(prof)fail("E_TARGET_PROFILE","la conversion de flotante a entero necesita omni_cast_float_to_int, un servicio de runtime que el perfil de destino no define");
                                std::string wide=av[0];
                                if(src.kind==Type::F32){ auto x=reg(); emit(x+" = fpext float "+wide+" to double"); wide=x; }
                                auto cv=reg(); emit(cv+" = call i64 @omni_cast_float_to_int(double "+wide+", i32 "+(isSignedInteger(dst)?"1":"0")+", i32 "+std::to_string(integerWidth(dst))+")");
                                if(integerWidth(dst)==64)return cv;
                                auto r=reg(); emit(r+" = trunc i64 "+cv+" to "+lt(dst)); return r;
                            }
                            fail("E_INTERNAL","cast numerico sin lowering");
                        }
                        if(e.resolved=="@builtin:resource.move") { auto moved=av[0]; consumePlace(e); return moved; }
                        if(e.resolved=="@builtin:resource.borrow"||e.resolved=="@builtin:resource.borrow_mut") return av[0];
                        if(e.resolved=="@builtin:bytes.from_text") { auto r=reg(); emit(r+" = call i64 @omni_bytes_from_text(i64 "+av[0]+")"); return r; }
                        if(e.resolved.rfind("@builtin:bit.",0)==0) {
                            const auto op=e.resolved.substr(13); const auto& ot=e.args[0].type; const auto ty=lt(ot); const auto width=integerWidth(ot); auto r=reg();
                            if(op=="and"||op=="or"||op=="xor") emit(r+" = "+op+" "+ty+" "+av[0]+", "+av[1]);
                            else if(op=="not") emit(r+" = xor "+ty+" "+av[0]+", -1");
                            else {
                                auto ok=reg(); emit(ok+" = icmp ult i32 "+av[1]+", "+std::to_string(width));
                                auto good=lab(),bad=lab(); emit("br i1 "+ok+", label %"+good+", label %"+bad); mark(bad); emit("call void @omni_trap_bounds()"); emit("unreachable"); mark(good);
                                std::string count=av[1];
                                if(width<32){ count=reg(); emit(count+" = trunc i32 "+av[1]+" to "+ty); }
                                else if(width>32){ count=reg(); emit(count+" = zext i32 "+av[1]+" to "+ty); }
                                emit(r+" = "+std::string(op=="shl"?"shl":(isSignedInteger(ot)?"ashr":"lshr"))+" "+ty+" "+av[0]+", "+count);
                            }
                            return r;
                        }
                        if(e.resolved=="@builtin:bytes.len") { auto r=reg(); emit(r+" = call i32 @omni_bytes_len(i64 "+av[0]+")"); return r; }
                        if(e.resolved=="@builtin:bytes.concat") { auto r=reg(); emit(r+" = call i64 @omni_bytes_concat(i64 "+av[0]+", i64 "+av[1]+")"); return r; }
                        if(e.resolved=="@builtin:bytes.to_text") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_bytes_to_text(i64 "+av[0]+", ptr "+outp+")"); auto tv=reg(); emit(tv+" = load i64, ptr "+outp); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+tv+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved.rfind("@builtin:simd.",0)==0) {
                            // CP-10 / MN-04 (spec/SIMD_BASELINE_CANDIDATE.md): the record of lanes is moved into an LLVM vector, the operation is the vector operation, the result goes back to a record.
                            // A freestanding image needs SSE2 for any of it (the same fence as floating point); hosted builds use the target's SSE2.
                            const std::string op=e.resolved.substr(14);
                            if(prof&&(prof->name!="baremetal-x86_64"||prof->isa!="sse2"))fail("E_TARGET_PROFILE",e.text+" requiere el perfil baremetal-x86_64 con --target-isa sse2 (los vectores usan registros SSE)");
                            const auto ltp=e.text.find('<'); const std::string inner=e.text.substr(ltp+1,e.text.size()-ltp-2);
                            std::string k1=inner,k2; if(const auto c=inner.find(','); c!=std::string::npos){ k1=inner.substr(0,c); k2=inner.substr(c+1); }
                            auto findRec=[&](const std::string& k)->const RecordDef& { for(const auto& r:p.records)if(r.key==k)return r; fail("E_INTERNAL","struct sin definicion: "+k); };
                            const RecordDef& vr=findRec(k1); const Type laneT=vr.fields.at(0).type; const size_t n=vr.fields.size();
                            Type vrT(Type::Record); vrT.key=k1; vrT.name=vr.name; Type mrT(Type::Record); mrT.key=k2; if(!k2.empty())mrT.name=findRec(k2).name;
                            const std::string sty=lt(vrT), lty=lt(laneT), vty="<"+std::to_string(n)+" x "+lty+">", bty="<"+std::to_string(n)+" x i1>", msty=k2.empty()?sty:lt(mrT);
                            const bool real=isFloat(laneT);
                            auto toVec=[&](const std::string& s,const std::string& st,const std::string& vt,const std::string& lt1)->std::string{
                                std::string acc="undef";
                                for(size_t i=0;i<n;++i){ auto x=reg(); emit(x+" = extractvalue "+st+" "+s+", "+std::to_string(i)); auto r=reg(); emit(r+" = insertelement "+vt+" "+acc+", "+lt1+" "+x+", i32 "+std::to_string(i)); acc=r; }
                                return acc;
                            };
                            auto fromVec=[&](const std::string& v,const std::string& st,const std::string& vt,const std::string& lt1)->std::string{
                                std::string acc="zeroinitializer";
                                for(size_t i=0;i<n;++i){ auto x=reg(); emit(x+" = extractelement "+vt+" "+v+", i32 "+std::to_string(i)); auto r=reg(); emit(r+" = insertvalue "+st+" "+acc+", "+lt1+" "+x+", "+std::to_string(i)); acc=r; }
                                return acc;
                            };
                            const std::string ftag=std::string("v")+std::to_string(n)+(lty=="float"?"f32":"f64");
                            auto constrainedVec=[&](const std::string& cop,const std::string& a,const std::string& b)->std::string{
                                lateDecls.insert("declare "+vty+" @llvm.experimental.constrained."+cop+"."+ftag+"("+vty+", "+vty+", metadata, metadata)");
                                auto r=reg(); emit(r+" = call "+vty+" @llvm.experimental.constrained."+cop+"."+ftag+"("+vty+" "+a+", "+vty+" "+b+", metadata !\"round.dynamic\", metadata !\"fpexcept.strict\") strictfp"); return r;
                            };
                            if(op=="splat") {
                                std::string acc="zeroinitializer";
                                for(size_t i=0;i<n;++i){ auto r=reg(); emit(r+" = insertvalue "+sty+" "+acc+", "+lty+" "+av[0]+", "+std::to_string(i)); acc=r; }
                                return acc;
                            }
                            if(op=="add"||op=="sub"||op=="mul"||op=="div") {
                                auto x=toVec(av[0],sty,vty,lty), y=toVec(av[1],sty,vty,lty); std::string r;
                                if(real) {
                                    const std::string fop=op=="add"?"fadd":(op=="sub"?"fsub":(op=="mul"?"fmul":"fdiv"));
                                    if(sse2())r=constrainedVec(fop,x,y); else { r=reg(); emit(r+" = "+fop+" "+vty+" "+x+", "+y); }
                                } else { r=reg(); emit(r+" = "+op+" "+vty+" "+x+", "+y); }
                                return fromVec(r,sty,vty,lty);
                            }
                            if(op=="and"||op=="or"||op=="xor") {
                                auto x=toVec(av[0],sty,vty,lty), y=toVec(av[1],sty,vty,lty); auto r=reg(); emit(r+" = "+op+" "+vty+" "+x+", "+y); return fromVec(r,sty,vty,lty);
                            }
                            if(op=="eq"||op=="ne"||op=="lt"||op=="le"||op=="gt"||op=="ge") {
                                auto x=toVec(av[0],sty,vty,lty), y=toVec(av[1],sty,vty,lty); auto r=reg();
                                if(real) {
                                    std::map<std::string,std::string> pred={{"eq","oeq"},{"ne","une"},{"lt","olt"},{"le","ole"},{"gt","ogt"},{"ge","oge"}};
                                    emit(r+" = fcmp "+pred.at(op)+" "+vty+" "+x+", "+y);
                                } else {
                                    const bool sg=isSignedInteger(laneT);
                                    std::map<std::string,std::string> pred={{"eq","eq"},{"ne","ne"},{"lt",sg?"slt":"ult"},{"le",sg?"sle":"ule"},{"gt",sg?"sgt":"ugt"},{"ge",sg?"sge":"uge"}};
                                    emit(r+" = icmp "+pred.at(op)+" "+vty+" "+x+", "+y);
                                }
                                // the mask record has the same number of bool lanes
                                std::string acc="zeroinitializer";
                                for(size_t i=0;i<n;++i){ auto b=reg(); emit(b+" = extractelement "+bty+" "+r+", i32 "+std::to_string(i)); auto s=reg(); emit(s+" = insertvalue "+msty+" "+acc+", i1 "+b+", "+std::to_string(i)); acc=s; }
                                return acc;
                            }
                            if(op=="select") {
                                auto m=toVec(av[0],msty,bty,"i1"), x=toVec(av[1],sty,vty,lty), y=toVec(av[2],sty,vty,lty); auto r=reg();
                                emit(r+" = select "+bty+" "+m+", "+vty+" "+x+", "+vty+" "+y); return fromVec(r,sty,vty,lty);
                            }
                            if(op=="mask_and"||op=="mask_or"||op=="mask_xor"||op=="mask_not") {
                                auto x=toVec(av[0],sty,bty,"i1"); auto r=reg();
                                if(op=="mask_not") { std::string ones="<"; for(size_t i=0;i<n;++i){ if(i)ones+=", "; ones+="i1 true"; } ones+=">"; emit(r+" = xor "+bty+" "+x+", "+ones); }
                                else { auto y=toVec(av[1],sty,bty,"i1"); emit(r+" = "+op.substr(5)+" "+bty+" "+x+", "+y); }
                                return fromVec(r,sty,bty,"i1");
                            }
                            if(op=="any"||op=="all"||op=="bitmask") {
                                auto x=toVec(av[0],sty,bty,"i1"); auto bits=reg(); emit(bits+" = bitcast "+bty+" "+x+" to i"+std::to_string(n));
                                if(op=="bitmask") { auto z=reg(); emit(z+" = zext i"+std::to_string(n)+" "+bits+" to i32"); return z; }
                                auto r=reg();
                                if(op=="any") emit(r+" = icmp ne i"+std::to_string(n)+" "+bits+", 0"); else emit(r+" = icmp eq i"+std::to_string(n)+" "+bits+", -1");
                                return r;
                            }
                            if(op=="reduce_add") {
                                auto x=toVec(av[0],sty,vty,lty); std::string acc;
                                for(size_t i=0;i<n;++i) {
                                    auto l=reg(); emit(l+" = extractelement "+vty+" "+x+", i32 "+std::to_string(i));
                                    if(i==0){ acc=l; continue; }
                                    if(real) { if(sse2())acc=constrainedBinary("fadd",lty,acc,l); else { auto r=reg(); emit(r+" = fadd "+lty+" "+acc+", "+l); acc=r; } }
                                    else { auto r=reg(); emit(r+" = add "+lty+" "+acc+", "+l); acc=r; }
                                }
                                return acc;
                            }
                            // load / store (memory.raw): lane i at address + i * width, volatile and unaligned; the _aligned forms trap (14) unless the address is 16-aligned; address 0 is never a vector
                            if(!prof)fail("E_TARGET_PROFILE",e.text+" requiere un perfil de destino bare-metal (--target-profile)");
                            const size_t w=real?(lty=="float"?4:8):integerWidth(laneT)/8;
                            auto nul=reg(); emit(nul+" = icmp eq i64 "+av[0]+", 0"); std::string bad=nul;
                            if(op=="load_aligned"||op=="store_aligned") { auto low=reg(); emit(low+" = and i64 "+av[0]+", 15"); auto mis=reg(); emit(mis+" = icmp ne i64 "+low+", 0"); bad=reg(); emit(bad+" = or i1 "+nul+", "+mis); }
                            auto gd=lab(),bl=lab(); emit("br i1 "+bad+", label %"+bl+", label %"+gd);
                            mark(bl); emit("call void @omni_fault(i32 14)"); emit("unreachable"); mark(gd);
                            auto lanePtr=[&](size_t i){ std::string fa=av[0]; if(i){ fa=reg(); emit(fa+" = add i64 "+av[0]+", "+std::to_string(i*w)); } auto ptr=reg(); emit(ptr+" = inttoptr i64 "+fa+" to ptr"); return ptr; };
                            if(op=="load"||op=="load_aligned") {
                                std::string acc="zeroinitializer";
                                for(size_t i=0;i<n;++i){ auto ptr=lanePtr(i); auto v=reg(); emit(v+" = load volatile "+lty+", ptr "+ptr+", align 1"); auto r=reg(); emit(r+" = insertvalue "+sty+" "+acc+", "+lty+" "+v+", "+std::to_string(i)); acc=r; }
                                return acc;
                            }
                            for(size_t i=0;i<n;++i){ auto fv=reg(); emit(fv+" = extractvalue "+sty+" "+av[1]+", "+std::to_string(i)); auto ptr=lanePtr(i); emit("store volatile "+lty+" "+fv+", ptr "+ptr+", align 1"); }
                            return "0";
                        }
                        if(e.resolved=="@builtin:layout.identity") {
                            const auto lt=e.text.find('<'); const auto key=e.text.substr(lt+1,e.text.size()-lt-2);
                            return std::to_string(recordIdentityWord(p,key,static_cast<unsigned>(e.binding)));
                        }
                        if(e.resolved=="@builtin:layout.size"||e.resolved=="@builtin:layout.align"||e.resolved=="@builtin:layout.offset"||e.resolved=="@builtin:raw.read"||e.resolved=="@builtin:raw.write") {
                            // CP-07 (NATIVE_LAYOUT_CANDIDATE.md): layout answers are constants computed by Omni under the target's C rules (the LLVM struct is only the oracle);
                            // typed access is field-by-field volatile, so a packed or unaligned record is never read through a falsely aligned reference, and padding is written as zero.
                            const auto ltp=e.text.find('<'); const auto rkey=e.text.substr(ltp+1,e.text.size()-ltp-2);
                            const unsigned maxAlign=(prof&&prof->triple.rfind("i386",0)==0)?4u:8u;
                            const auto lay=recordLayout(p,rkey,maxAlign);
                            if(e.resolved=="@builtin:layout.size")return std::to_string(lay.size);
                            if(e.resolved=="@builtin:layout.align")return std::to_string(lay.align);
                            if(e.resolved=="@builtin:layout.offset")return std::to_string(lay.offsets.at(static_cast<size_t>(e.binding)));
                            if(!prof)fail("E_TARGET_PROFILE",e.text+" requiere un perfil de destino bare-metal (--target-profile)");
                            auto recordType=[&](const std::string& k){ Type t(Type::Record); t.key=k; return t; };
                            auto findRecord=[&](const std::string& k)->const RecordDef& { for(const auto& r:p.records)if(r.key==k)return r; fail("E_INTERNAL","struct sin definicion: "+k); };
                            std::function<std::string(const std::string&,const std::string&)> readRecord=[&](const std::string& k,const std::string& addr)->std::string {
                                const auto& rec=findRecord(k); const auto rl=recordLayout(p,k,maxAlign); std::string acc="zeroinitializer";
                                for(size_t i=0;i<rec.fields.size();++i) {
                                    std::string fa=addr;
                                    if(rl.offsets[i]) { fa=reg(); emit(fa+" = add i64 "+addr+", "+std::to_string(rl.offsets[i])); }
                                    std::string v;
                                    if(isInteger(rec.fields[i].type)) { auto ptr=reg(); emit(ptr+" = inttoptr i64 "+fa+" to ptr"); v=reg(); emit(v+" = load volatile "+lt(rec.fields[i].type)+", ptr "+ptr+", align 1"); }
                                    else v=readRecord(rec.fields[i].type.key,fa);
                                    auto r=reg(); emit(r+" = insertvalue "+lt(recordType(k))+" "+acc+", "+lt(rec.fields[i].type)+" "+v+", "+std::to_string(i)); acc=r;
                                }
                                return acc;
                            };
                            std::function<void(const std::string&,const std::string&,const std::string&)> writeRecord=[&](const std::string& k,const std::string& addr,const std::string& value) {
                                const auto& rec=findRecord(k); const auto rl=recordLayout(p,k,maxAlign);
                                for(const auto& gap:rl.padding)for(uint64_t b=0;b<gap.second;++b) {
                                    auto pa=reg(); emit(pa+" = add i64 "+addr+", "+std::to_string(gap.first+b));
                                    auto pp=reg(); emit(pp+" = inttoptr i64 "+pa+" to ptr"); emit("store volatile i8 0, ptr "+pp+", align 1");
                                }
                                for(size_t i=0;i<rec.fields.size();++i) {
                                    std::string fa=addr;
                                    if(rl.offsets[i]) { fa=reg(); emit(fa+" = add i64 "+addr+", "+std::to_string(rl.offsets[i])); }
                                    auto fv=reg(); emit(fv+" = extractvalue "+lt(recordType(k))+" "+value+", "+std::to_string(i));
                                    if(isInteger(rec.fields[i].type)) { auto ptr=reg(); emit(ptr+" = inttoptr i64 "+fa+" to ptr"); emit("store volatile "+lt(rec.fields[i].type)+" "+fv+", ptr "+ptr+", align 1"); }
                                    else writeRecord(rec.fields[i].type.key,fa,fv);
                                }
                            };
                            // a native record is accessed at its alignment (trap 14 otherwise); address 0 is never a record
                            auto nul=reg(); emit(nul+" = icmp eq i64 "+av[0]+", 0"); std::string bad=nul;
                            if(lay.align>1) { auto low=reg(); emit(low+" = and i64 "+av[0]+", "+std::to_string(lay.align-1)); auto mis=reg(); emit(mis+" = icmp ne i64 "+low+", 0"); bad=reg(); emit(bad+" = or i1 "+nul+", "+mis); }
                            auto gd=lab(),bl=lab(); emit("br i1 "+bad+", label %"+bl+", label %"+gd);
                            mark(bl); emit("call void @omni_fault(i32 14)"); emit("unreachable"); mark(gd);
                            if(e.resolved=="@builtin:raw.read")return readRecord(rkey,av[0]);
                            writeRecord(rkey,av[0],av[1]);
                            return "0";
                        }
                        if(e.resolved.rfind("@builtin:raw.",0)==0||e.resolved.rfind("@builtin:port.",0)==0||e.resolved.rfind("@builtin:cpu.",0)==0||e.resolved.rfind("@builtin:atomic.",0)==0||
                           e.resolved.rfind("@builtin:tls.",0)==0||e.resolved.rfind("@builtin:pcpu.",0)==0) {
                            if(!prof)fail("E_TARGET_PROFILE",e.text+" requiere un perfil de destino bare-metal (--target-profile)");
                            const auto& r0=e.resolved;
                            if(r0=="@builtin:tls.get"||r0=="@builtin:tls.set"||r0=="@builtin:tls.block_size"||r0=="@builtin:tls.init"||r0=="@builtin:tls.teardown") {
                                // CP-11 typed surface (THREAD_LOCAL_CANDIDATE.md). The compiler owns the layout; every access is checked against the block header.
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE",e.text+" requiere el perfil baremetal-x86_64");
                                const auto layout=threadLocalLayout(p);
                                const std::string magicValue="3554268455816285519";
                                auto checkBlock=[&](uint64_t needed) {
                                    auto magic=reg(); emit(magic+" = call i64 asm sideeffect \"movq %fs:0, $0\", \"=r,~{memory}\"()");
                                    auto bad=reg(); emit(bad+" = icmp ne i64 "+magic+", "+magicValue);
                                    if(needed) {
                                        auto sz=reg(); emit(sz+" = call i64 asm sideeffect \"movq %fs:8, $0\", \"=r,~{memory}\"()");
                                        auto past=reg(); emit(past+" = icmp ult i64 "+sz+", "+std::to_string(needed));
                                        auto either=reg(); emit(either+" = or i1 "+bad+", "+past); bad=either;
                                    }
                                    auto gd=lab(),bl=lab(); emit("br i1 "+bad+", label %"+bl+", label %"+gd);
                                    mark(bl); emit("call void @omni_fault(i32 13)"); emit("unreachable"); mark(gd);
                                };
                                if(r0=="@builtin:tls.block_size")return std::to_string(layout.size);
                                if(r0=="@builtin:tls.init") {
                                    // copy the template image (header + initial values) over the block; the caller owns the memory
                                    // a block starts on a 16-byte boundary and never at address 0
                                    auto low=reg(); emit(low+" = and i64 "+av[0]+", 15");
                                    auto skew=reg(); emit(skew+" = icmp ne i64 "+low+", 0");
                                    auto zero=reg(); emit(zero+" = icmp eq i64 "+av[0]+", 0");
                                    auto badBase=reg(); emit(badBase+" = or i1 "+skew+", "+zero);
                                    auto okBase=lab(),faultBase=lab(); emit("br i1 "+badBase+", label %"+faultBase+", label %"+okBase);
                                    mark(faultBase); emit("call void @omni_fault(i32 13)"); emit("unreachable"); mark(okBase);
                                    auto src=reg(); emit(src+" = ptrtoint ptr @omni.tls.template to i64");
                                    auto cp=reg(); emit(cp+" = call { i64, i64, i64 } asm sideeffect \"cld\\0Arep movsq\", \"={rdi},={rsi},={rcx},0,1,2,~{memory},~{dirflag}\"(i64 "+av[0]+", i64 "+src+", i64 "+std::to_string(layout.size/8)+")");
                                    return std::to_string(layout.size);
                                }
                                if(r0=="@builtin:tls.teardown") {
                                    checkBlock(0);
                                    emit("call void asm sideeffect \"movq $$0, %fs:0\", \"~{memory}\"()");
                                    return "0";
                                }
                                const auto ord=orderedThreadLocals(p); size_t idx=ord.size();
                                for(size_t i=0;i<ord.size();++i)if("@tls:"+ord[i]->module+"."+ord[i]->name==e.args[0].resolved)idx=i;
                                if(idx==ord.size())fail("E_INTERNAL","thread_local sin layout: "+e.args[0].resolved);
                                const auto& vt=ord[idx]->type; const unsigned width=integerWidth(vt)/8; const auto off=std::to_string(layout.offsets[idx]);
                                const std::string suffix=width==8?"q":(width==4?"l":(width==2?"w":"b"));
                                checkBlock(layout.offsets[idx]+width);
                                if(r0=="@builtin:tls.get") {
                                    auto v=reg();
                                    if(width==8)emit(v+" = call i64 asm sideeffect \"movq %fs:"+off+", $0\", \"=r,~{memory}\"()");
                                    else {
                                        auto w=reg(); emit(w+" = call i32 asm sideeffect \"mov"+std::string(width==4?"l":(width==2?"zwl":"zbl"))+" %fs:"+off+", $0\", \"=r,~{memory}\"()");
                                        if(width==4)return w;
                                        emit(v+" = trunc i32 "+w+" to "+lt(vt));
                                    }
                                    return v;
                                }
                                emit("call void asm sideeffect \"mov"+suffix+" $0, %fs:"+off+"\", \"r,~{memory}\"("+lt(vt)+" "+av[1]+")");
                                return "0";
                            }
                            if(r0.rfind("@builtin:tls.",0)==0||r0.rfind("@builtin:pcpu.",0)==0) {
                                // CP-11: segment-relative access to a block with a 16-byte header: seg:0 = magic ("OMNITLS1" / "OMNIPCP1"), seg:8 = size.
                                // An unset base (0) reads the real-mode vector table, never the magic, so it faults instead of accessing low memory.
                                // Offsets inside the header, past the size or wrapping are trap code 13; nothing is accessed before that check.
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE",e.text+" requiere el perfil baremetal-x86_64");
                                const bool tls=r0.rfind("@builtin:tls.",0)==0; const std::string seg=tls?"fs":"gs"; const std::string op=r0.substr(tls?13:14);
                                const bool w64=op.compare(op.size()-2,2,"64")==0; const std::string width=w64?"8":"4";
                                auto magic=reg(); emit(magic+" = call i64 asm sideeffect \"movq %"+seg+":0, $0\", \"=r,~{memory}\"()");
                                auto sz=reg(); emit(sz+" = call i64 asm sideeffect \"movq %"+seg+":8, $0\", \"=r,~{memory}\"()");
                                auto nomagic=reg(); emit(nomagic+" = icmp ne i64 "+magic+", "+(tls?"3554268455816285519":"3553414118101634383"));
                                auto small=reg(); emit(small+" = icmp ult i64 "+av[0]+", 16");
                                auto end=reg(); emit(end+" = add i64 "+av[0]+", "+width);
                                auto wrap=reg(); emit(wrap+" = icmp ult i64 "+end+", "+av[0]);
                                auto past=reg(); emit(past+" = icmp ugt i64 "+end+", "+sz);
                                auto b0=reg(); emit(b0+" = or i1 "+nomagic+", "+small);
                                auto b1=reg(); emit(b1+" = or i1 "+b0+", "+wrap); auto bad=reg(); emit(bad+" = or i1 "+b1+", "+past);
                                auto gd=lab(),bl=lab(); emit("br i1 "+bad+", label %"+bl+", label %"+gd);
                                mark(bl); emit("call void @omni_fault(i32 13)"); emit("unreachable"); mark(gd);
                                if(op=="load32") { auto v=reg(); emit(v+" = call i32 asm sideeffect \"movl %"+seg+":($1), $0\", \"=r,r,~{memory}\"(i64 "+av[0]+")"); return v; }
                                if(op=="load64") { auto v=reg(); emit(v+" = call i64 asm sideeffect \"movq %"+seg+":($1), $0\", \"=r,r,~{memory}\"(i64 "+av[0]+")"); return v; }
                                if(op=="store32") { emit("call void asm sideeffect \"movl $1, %"+seg+":($0)\", \"r,r,~{memory}\"(i64 "+av[0]+", i32 "+av[1]+")"); return "0"; }
                                emit("call void asm sideeffect \"movq $1, %"+seg+":($0)\", \"r,r,~{memory}\"(i64 "+av[0]+", i64 "+av[1]+")"); return "0";
                            }
                            if(r0.rfind("@builtin:atomic.",0)==0) {
                                static const char* ordn[]={"monotonic","acquire","release","acq_rel","seq_cst"};
                                const std::string op=r0.substr(16);
                                if(op=="fence") { emit(std::string("fence ")+ordn[e.args[0].value]); return "0"; }
                                const bool w64=op.compare(op.size()-2,2,"64")==0; const std::string ity=w64?"i64":"i32"; const std::string al=w64?"8":"4"; const std::string msk=w64?"7":"3";
                                // natural alignment and non-null are checked before the access; violation = trap code 11 (atomic access fault)
                                auto am=reg(); emit(am+" = and i64 "+av[0]+", "+msk);
                                auto mis=reg(); emit(mis+" = icmp ne i64 "+am+", 0");
                                auto nul=reg(); emit(nul+" = icmp eq i64 "+av[0]+", 0");
                                auto bd=reg(); emit(bd+" = or i1 "+mis+", "+nul);
                                auto gd=lab(),bl=lab(); emit("br i1 "+bd+", label %"+bl+", label %"+gd);
                                mark(bl); emit("call void @omni_fault(i32 11)"); emit("unreachable"); mark(gd);
                                auto ptr=reg(); emit(ptr+" = inttoptr i64 "+av[0]+" to ptr");
                                if(op.rfind("load",0)==0) { auto v=reg(); emit(v+" = load atomic volatile "+ity+", ptr "+ptr+" "+ordn[e.args[1].value]+", align "+al); return v; }
                                if(op.rfind("store",0)==0) { emit("store atomic volatile "+ity+" "+av[1]+", ptr "+ptr+" "+ordn[e.args[2].value]+", align "+al); return "0"; }
                                if(op.rfind("fetch_add",0)==0) { auto v=reg(); emit(v+" = atomicrmw volatile add ptr "+ptr+", "+ity+" "+av[1]+" "+ordn[e.args[2].value]+", align "+al); return v; }
                                auto pr=reg(); emit(pr+" = cmpxchg volatile ptr "+ptr+", "+ity+" "+av[1]+", "+ity+" "+av[2]+" "+ordn[e.args[3].value]+" "+ordn[e.args[4].value]+", align "+al);
                                auto ov=reg(); emit(ov+" = extractvalue { "+ity+", i1 } "+pr+", 0"); return ov;
                            }
                            if(r0=="@builtin:raw.load8"||r0=="@builtin:raw.load32"||r0=="@builtin:raw.load64") {
                                const std::string ity=r0=="@builtin:raw.load8"?"i8":(r0=="@builtin:raw.load32"?"i32":"i64");
                                auto ptr=reg(); emit(ptr+" = inttoptr i64 "+av[0]+" to ptr");
                                auto v=reg(); emit(v+" = load volatile "+ity+", ptr "+ptr+", align 1");
                                if(ity=="i8"){ auto z=reg(); emit(z+" = zext i8 "+v+" to i32"); return z; }
                                return v;
                            }
                            if(r0=="@builtin:raw.store8"||r0=="@builtin:raw.store32"||r0=="@builtin:raw.store64") {
                                const std::string ity=r0=="@builtin:raw.store8"?"i8":(r0=="@builtin:raw.store32"?"i32":"i64");
                                std::string value=av[1];
                                if(ity=="i8") {
                                    auto ok=reg(),good=lab(),bad=lab(); emit(ok+" = icmp ule i32 "+av[1]+", 255"); emit("br i1 "+ok+", label %"+good+", label %"+bad);
                                    mark(bad); emit("call void @omni_fault(i32 4)"); emit("unreachable"); mark(good);
                                    auto t8=reg(); emit(t8+" = trunc i32 "+av[1]+" to i8"); value=t8;
                                }
                                auto ptr=reg(); emit(ptr+" = inttoptr i64 "+av[0]+" to ptr");
                                emit("store volatile "+ity+" "+value+", ptr "+ptr+", align 1");
                                return "0";
                            }
                            if(r0=="@builtin:port.in8") {
                                auto p16=reg(); emit(p16+" = trunc i32 "+av[0]+" to i16");
                                auto v=reg(); emit(v+" = call i8 asm sideeffect \"inb %dx, %al\", \"={al},{dx},~{memory}\"(i16 "+p16+")");
                                auto z=reg(); emit(z+" = zext i8 "+v+" to i32"); return z;
                            }
                            if(r0=="@builtin:port.in16"||r0=="@builtin:port.in32"||r0=="@builtin:port.out16") {
                                // Exact-width x86 port access (TARGET_BAREMETAL_PROFILE_CANDIDATE.md). No byte fallback: wider port operations have
                                // per-width side effects. The port is the low 16 bits (DX); out16 writes the low 16 bits of the value, like out8/out32
                                // truncate the value to the port width.
                                auto p16=reg(); emit(p16+" = trunc i32 "+av[0]+" to i16");
                                if(r0=="@builtin:port.out16") {
                                    auto v16=reg(); emit(v16+" = trunc i32 "+av[1]+" to i16");
                                    emit("call void asm sideeffect \"outw %ax, %dx\", \"{ax},{dx},~{memory}\"(i16 "+v16+", i16 "+p16+")"); return "0";
                                }
                                if(r0=="@builtin:port.in32") {
                                    auto v=reg(); emit(v+" = call i32 asm sideeffect \"inl %dx, %eax\", \"={eax},{dx},~{memory}\"(i16 "+p16+")"); return v;
                                }
                                auto v=reg(); emit(v+" = call i16 asm sideeffect \"inw %dx, %ax\", \"={ax},{dx},~{memory}\"(i16 "+p16+")");
                                auto z=reg(); emit(z+" = zext i16 "+v+" to i32"); return z;
                            }
                            if(r0=="@builtin:port.out8") {
                                auto p16=reg(),v8=reg(); emit(p16+" = trunc i32 "+av[0]+" to i16"); emit(v8+" = trunc i32 "+av[1]+" to i8");
                                emit("call void asm sideeffect \"outb %al, %dx\", \"{al},{dx},~{memory}\"(i8 "+v8+", i16 "+p16+")"); return "0";
                            }
                            if(r0=="@builtin:port.out32") {
                                auto p16=reg(); emit(p16+" = trunc i32 "+av[0]+" to i16");
                                emit("call void asm sideeffect \"outl %eax, %dx\", \"{eax},{dx},~{memory}\"(i32 "+av[1]+", i16 "+p16+")"); return "0";
                            }
                            if(r0=="@builtin:cpu.halt") {
                                emit("call void asm sideeffect \"cli; hlt\", \"~{memory}\"()"); emit("unreachable"); mark(lab()); return "0";
                            }
                            if(r0=="@builtin:cpu.fxsave"||r0=="@builtin:cpu.fxrstor"||r0=="@builtin:cpu.read_mxcsr"||r0=="@builtin:cpu.write_mxcsr"||r0=="@builtin:cpu.fninit") {
                                // CP-10 (FPU_SSE_STATE_CANDIDATE.md): x87/SSE state primitives. A violated rule is trap code 12, never a hardware #GP.
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE",e.text+" requiere el perfil baremetal-x86_64");
                                if(prof->isa!="sse2")fail("E_TARGET_PROFILE",e.text+" requiere --target-isa sse2");
                                auto stateFault=[&](const std::string& cond){
                                    auto gd=lab(),bl=lab(); emit("br i1 "+cond+", label %"+bl+", label %"+gd);
                                    mark(bl); emit("call void @omni_fault(i32 12)"); emit("unreachable"); mark(gd);
                                };
                                auto badArea=[&](const std::string& a){
                                    auto am=reg(); emit(am+" = and i64 "+a+", 15"); auto mis=reg(); emit(mis+" = icmp ne i64 "+am+", 0");
                                    auto nul=reg(); emit(nul+" = icmp eq i64 "+a+", 0"); auto bd=reg(); emit(bd+" = or i1 "+mis+", "+nul); return bd;
                                };
                                if(r0=="@builtin:cpu.fninit") { emit("call void asm sideeffect \"fninit\", \"~{memory}\"()"); return "0"; }
                                if(r0=="@builtin:cpu.read_mxcsr") {
                                    auto slot=reg(); hoist(slot,"i32"); emit("store i32 0, ptr "+slot);
                                    emit("call void asm sideeffect \"stmxcsr $0\", \"=*m,~{memory}\"(ptr elementtype(i32) "+slot+")");
                                    auto v=reg(); emit(v+" = load volatile i32, ptr "+slot); return v;
                                }
                                if(r0=="@builtin:cpu.write_mxcsr") {
                                    // reserved MXCSR bits (anything outside 0xFFBF) are rejected before ldmxcsr
                                    auto bad=reg(); emit(bad+" = and i32 "+av[0]+", -65472"); auto nz=reg(); emit(nz+" = icmp ne i32 "+bad+", 0"); stateFault(nz);
                                    auto slot=reg(); hoist(slot,"i32"); emit("store i32 "+av[0]+", ptr "+slot);
                                    emit("call void asm sideeffect \"ldmxcsr $0\", \"*m,~{memory}\"(ptr elementtype(i32) "+slot+")"); return "0";
                                }
                                stateFault(badArea(av[0]));
                                if(r0=="@builtin:cpu.fxsave") { emit("call void asm sideeffect \"fxsave64 ($0)\", \"r,~{memory}\"(i64 "+av[0]+")"); return "0"; }
                                // fxrstor: the saved MXCSR (offset 24) must fit the image's MXCSR_MASK (offset 28; 0 means 0xFFBF) or the restore is rejected
                                auto a24=reg(); emit(a24+" = add i64 "+av[0]+", 24"); auto p24=reg(); emit(p24+" = inttoptr i64 "+a24+" to ptr");
                                auto m=reg(); emit(m+" = load volatile i32, ptr "+p24+", align 1");
                                auto a28=reg(); emit(a28+" = add i64 "+av[0]+", 28"); auto p28=reg(); emit(p28+" = inttoptr i64 "+a28+" to ptr");
                                auto mk=reg(); emit(mk+" = load volatile i32, ptr "+p28+", align 1");
                                auto z=reg(); emit(z+" = icmp eq i32 "+mk+", 0"); auto eff=reg(); emit(eff+" = select i1 "+z+", i32 65471, i32 "+mk);
                                auto inv=reg(); emit(inv+" = xor i32 "+eff+", -1"); auto bad=reg(); emit(bad+" = and i32 "+m+", "+inv);
                                auto nz=reg(); emit(nz+" = icmp ne i32 "+bad+", 0"); stateFault(nz);
                                emit("call void asm sideeffect \"fxrstor64 ($0)\", \"r,~{memory}\"(i64 "+av[0]+")"); return "0";
                            }
                            if(r0=="@builtin:cpu.set_stack") { emit("call void asm sideeffect \"movl $0, %esp\", \"r,~{memory}\"(i32 "+av[0]+")"); return "0"; }
                            if(r0=="@builtin:cpu.lgdt") { emit("call void asm sideeffect \"lgdt ($0)\", \"r,~{memory}\"(i32 "+av[0]+")"); return "0"; }
                            if(r0=="@builtin:cpu.write_cr") {
                                const auto n=std::to_string(e.args[0].value);
                                if(prof->name=="baremetal-x86_64") {
                                    // 64-bit mode only encodes `mov r64, crN`: widen the u32 operand (zero-extended).
                                    auto w=reg(); emit(w+" = zext i32 "+av[1]+" to i64");
                                    emit("call void asm sideeffect \"movq $0, %cr"+n+"\", \"r,~{memory}\"(i64 "+w+")"); return "0";
                                }
                                emit("call void asm sideeffect \"movl $0, %cr"+n+"\", \"r,~{memory}\"(i32 "+av[1]+")"); return "0";
                            }
                            if(r0=="@builtin:cpu.read_cr") {
                                const auto n=std::to_string(e.args[0].value); auto v=reg();
                                if(prof->name=="baremetal-x86_64") {
                                    // the u32 result is the low half of the control register
                                    auto q=reg(); emit(q+" = call i64 asm sideeffect \"movq %cr"+n+", $0\", \"=r,~{memory}\"()");
                                    emit(v+" = trunc i64 "+q+" to i32"); return v;
                                }
                                emit(v+" = call i32 asm sideeffect \"movl %cr"+n+", $0\", \"=r,~{memory}\"()"); return v;
                            }
                            if(r0=="@builtin:cpu.switch_context"||r0=="@builtin:cpu.thread_trampoline") {
                                if(!prof||prof->threadEntry.empty())fail("E_TARGET_PROFILE",e.text+" requiere --thread-entry");
                                auto v=reg();
                                if(r0=="@builtin:cpu.switch_context") emit(v+" = call i64 @omni_switch_context(i64 "+av[0]+", i64 "+av[1]+")");
                                else emit(v+" = ptrtoint ptr @omni_thread_trampoline to i64");
                                return v;
                            }
                            if(r0=="@builtin:cpu.sti") { emit("call void asm sideeffect \"sti\", \"~{memory}\"()"); return "0"; }
                            if(r0=="@builtin:cpu.cli") { emit("call void asm sideeffect \"cli\", \"~{memory}\"()"); return "0"; }
                            if(r0=="@builtin:cpu.wait_irq") { emit("call void asm sideeffect \"sti\\0Ahlt\\0Acli\", \"~{memory}\"()"); return "0"; }
                            if(r0=="@builtin:cpu.ltr") { auto w=reg(); emit(w+" = trunc i32 "+av[0]+" to i16"); emit("call void asm sideeffect \"ltr $0\", \"r,~{memory}\"(i16 "+w+")"); return "0"; }
                            if(r0=="@builtin:cpu.enter_ring3"||r0=="@builtin:cpu.enter_ring3_interruptible"||r0=="@builtin:cpu.leave_ring3") {
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE",e.text+" requiere el perfil baremetal-x86_64");
                                if(!prof->ring3Support)fail("E_TARGET_PROFILE",e.text+" requiere --ring3-support");
                                auto v=reg();
                                if(r0=="@builtin:cpu.enter_ring3_interruptible") {
                                    // Same contract as enter_ring3 (area layout, iretq frame, every other register cleared, left through
                                    // omni_leave_ring3) except RFLAGS = 0x202: IF=1 while at CPL3, IOPL=0. The stub is appended to `globals`
                                    // only for programs that use it, so every other program keeps byte-identical IR.
                                    if(globals.str().find("@omni_enter_ring3_interruptible")==std::string::npos) {
                                        globals<<"\ndeclare i64 @omni_enter_ring3_interruptible(i64, i64, i64)\n";
                                        globals<<"module asm \".text\\0A.globl omni_enter_ring3_interruptible\\0Aomni_enter_ring3_interruptible:\\0Amovq %rbx, 0(%rdx)\\0Amovq %rbp, 8(%rdx)\\0Amovq %r12, 16(%rdx)\\0Amovq %r13, 24(%rdx)\\0Amovq %r14, 32(%rdx)\\0Amovq %r15, 40(%rdx)\\0Amovq %rsp, 48(%rdx)\\0A"
                                          <<"pushq $27\\0Apushq %rsi\\0Apushq $514\\0Apushq $35\\0Apushq %rdi\\0Axorl %eax, %eax\\0Axorl %ebx, %ebx\\0Axorl %ecx, %ecx\\0Axorl %edx, %edx\\0Axorl %esi, %esi\\0Axorl %edi, %edi\\0Axorl %ebp, %ebp\\0A"
                                          <<"xorl %r8d, %r8d\\0Axorl %r9d, %r9d\\0Axorl %r10d, %r10d\\0Axorl %r11d, %r11d\\0Axorl %r12d, %r12d\\0Axorl %r13d, %r13d\\0Axorl %r14d, %r14d\\0Axorl %r15d, %r15d\\0Airetq\\0A\"\n";
                                    }
                                    emit(v+" = call i64 @omni_enter_ring3_interruptible(i64 "+av[0]+", i64 "+av[1]+", i64 "+av[2]+")");
                                }
                                else if(r0=="@builtin:cpu.enter_ring3") emit(v+" = call i64 @omni_enter_ring3(i64 "+av[0]+", i64 "+av[1]+", i64 "+av[2]+")");
                                else emit(v+" = call i64 @omni_leave_ring3(i64 "+av[0]+", i64 "+av[1]+")");
                                return v;
                            }
                            if(r0=="@builtin:cpu.trap3") {
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","cpu.trap3 requiere el perfil baremetal-x86_64");
                                auto v=reg(); emit(v+" = call i64 asm sideeffect \"int $$"+std::to_string(e.args[0].value)+"\", \"={ax},{ax},{di},{si},~{memory}\"(i64 "+av[1]+", i64 "+av[2]+", i64 "+av[3]+")"); return v;
                            }
                            if(r0=="@builtin:cpu.rdtsc") {
                                auto agg=reg(); emit(agg+" = call { i32, i32 } asm sideeffect \"rdtsc\", \"={ax},={dx},~{memory}\"()");
                                auto lo=reg(),hi=reg(),l64=reg(),h64=reg(),hs=reg(),v=reg();
                                emit(lo+" = extractvalue { i32, i32 } "+agg+", 0"); emit(hi+" = extractvalue { i32, i32 } "+agg+", 1");
                                emit(l64+" = zext i32 "+lo+" to i64"); emit(h64+" = zext i32 "+hi+" to i64");
                                emit(hs+" = shl i64 "+h64+", 32"); emit(v+" = or i64 "+hs+", "+l64); return v;
                            }
                            if(r0=="@builtin:cpu.read_flags") {
                                // pushfq/pop uses the stack: freestanding images are built without a red zone (-mno-red-zone), as the profile requires
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","cpu.read_flags requiere el perfil baremetal-x86_64");
                                auto v=reg(); emit(v+" = call i64 asm sideeffect \"pushfq\\0Apopq $0\", \"=r,~{memory}\"()"); return v;
                            }
                            if(r0=="@builtin:cpu.read_cr64") {
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","cpu.read_cr64 requiere el perfil baremetal-x86_64");
                                auto v=reg(); emit(v+" = call i64 asm sideeffect \"movq %cr"+std::to_string(e.args[0].value)+", $0\", \"=r,~{memory}\"()"); return v;
                            }
                            if(r0=="@builtin:cpu.lidt") {
                                if(prof->name=="baremetal-x86_64") { auto w=reg(); emit(w+" = zext i32 "+av[0]+" to i64"); emit("call void asm sideeffect \"lidt ($0)\", \"r,~{memory}\"(i64 "+w+")"); }
                                else emit("call void asm sideeffect \"lidt ($0)\", \"r,~{memory}\"(i32 "+av[0]+")");
                                return "0";
                            }
                            if(r0=="@builtin:cpu.rdmsr") {
                                auto agg=reg(); emit(agg+" = call { i32, i32 } asm sideeffect \"rdmsr\", \"={ax},={dx},{cx},~{memory}\"(i32 "+av[0]+")");
                                auto v=reg(); emit(v+" = extractvalue { i32, i32 } "+agg+", "+std::to_string(e.args[1].value)); return v;
                            }
                            if(r0=="@builtin:cpu.cpuid_sub") {
                                auto agg=reg(); emit(agg+" = call { i32, i32, i32, i32 } asm sideeffect \"cpuid\", \"={ax},={bx},={cx},={dx},{ax},{cx},~{memory}\"(i32 "+av[0]+", i32 "+av[1]+")");
                                auto v=reg(); emit(v+" = extractvalue { i32, i32, i32, i32 } "+agg+", "+std::to_string(e.args[2].value)); return v;
                            }
                            if(r0=="@builtin:cpu.cpuid") {
                                auto agg=reg(); emit(agg+" = call { i32, i32, i32, i32 } asm sideeffect \"cpuid\", \"={ax},={bx},={cx},={dx},{ax},{cx},~{memory}\"(i32 "+av[0]+", i32 0)");
                                auto v=reg(); emit(v+" = extractvalue { i32, i32, i32, i32 } "+agg+", "+std::to_string(e.args[1].value)); return v;
                            }
                            if(r0=="@builtin:cpu.call_addr") {
                                if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","cpu.call_addr requiere el perfil baremetal-x86_64");
                                auto v=reg(); emit(v+" = call i32 asm sideeffect \"call *$1\", \"={ax},r,~{rcx},~{rdx},~{rsi},~{rdi},~{r8},~{r9},~{r10},~{r11},~{memory}\"(i64 "+av[0]+")"); return v;
                            }
                            if(r0=="@builtin:cpu.wrmsr") { emit("call void asm sideeffect \"wrmsr\", \"{ecx},{eax},{edx},~{memory}\"(i32 "+av[0]+", i32 "+av[1]+", i32 "+av[2]+")"); return "0"; }
                            if(r0=="@builtin:cpu.far_jump") {
                                emit("call void asm sideeffect \"ljmpl $$"+std::to_string(e.args[0].value)+", $$"+std::to_string(e.args[1].value)+"\", \"~{memory}\"()"); emit("unreachable"); mark(lab()); return "0";
                            }
                            fail("E_INTERNAL","primitiva de destino sin lowering: "+e.text);
                        }
                        if(e.resolved=="@builtin:buffer.alloc") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_buffer_alloc(i32 "+av[0]+", ptr "+outp+")"); auto hv=reg(); emit(hv+" = load i64, ptr "+outp); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+hv+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.len") { auto r=reg(); emit(r+" = call i32 @omni_buffer_len(i64 "+av[0]+")"); return r; }
                        if(e.resolved=="@builtin:buffer.read_u32le"||e.resolved=="@builtin:buffer.read_u64le") {
                            const bool wide=e.resolved=="@builtin:buffer.read_u64le"; const std::string ity=wide?"i64":"i32";
                            auto outp=reg(); hoist(outp,ity); emit("store "+ity+" 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_buffer_read_"+std::string(wide?"u64le":"u32le")+"(i64 "+av[0]+", i32 "+av[1]+", ptr "+outp+")"); auto bv=reg(); emit(bv+" = load "+ity+", ptr "+outp); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", "+ity+" "+bv+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.write_u32le"||e.resolved=="@builtin:buffer.write_u64le") {
                            const bool wide=e.resolved=="@builtin:buffer.write_u64le"; const std::string ity=wide?"i64":"i32";
                            auto er=reg(); emit(er+" = call i32 @omni_buffer_write_"+std::string(wide?"u64le":"u32le")+"(i64 "+av[0]+", i32 "+av[1]+", "+ity+" "+av[2]+")"); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 1, 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.read_u8") {
                            auto outp=reg(); hoist(outp,"i32"); emit("store i32 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_buffer_read_u8(i64 "+av[0]+", i32 "+av[1]+", ptr "+outp+")"); auto bv=reg(); emit(bv+" = load i32, ptr "+outp); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+bv+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.write_u8") {
                            auto er=reg(); emit(er+" = call i32 @omni_buffer_write_u8(i64 "+av[0]+", i32 "+av[1]+", i32 "+av[2]+")"); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 1, 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.grow") {
                            lateDecls.insert("declare i32 @omni_buffer_grow(i64, i32, ptr)"); if(prof)fail("E_TARGET_PROFILE","buffer.grow solo esta definido en el perfil hospedado; un perfil de destino no define un allocator de Core");
                            auto outp=reg(); hoist(outp,"i32"); emit("store i32 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_buffer_grow(i64 "+av[0]+", i32 "+av[1]+", ptr "+outp+")"); auto bv=reg(); emit(bv+" = load i32, ptr "+outp); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+bv+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.zero") {
                            lateDecls.insert("declare i32 @omni_buffer_zero(i64, i32, i32)"); if(prof)fail("E_TARGET_PROFILE","buffer.zero solo esta definido en el perfil hospedado; un perfil de destino no define un allocator de Core");
                            auto er=reg(); emit(er+" = call i32 @omni_buffer_zero(i64 "+av[0]+", i32 "+av[1]+", i32 "+av[2]+")"); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 1, 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved=="@builtin:buffer.freeze") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_buffer_freeze(i64 "+av[0]+", ptr "+outp+")"); auto bv=reg(); emit(bv+" = load i64, ptr "+outp); auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0"); auto r0=reg(),r1=reg(),r2=reg(); emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+bv+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2"); return r2;
                        }
                        if(e.resolved.rfind("@builtin:slots.",0)==0) {   // CP-01/CP-04 (OWNED_SLOTS_CANDIDATE.md): resource handles move between owners; the tag keeps a buffer to one type
                            if(prof)fail("E_TARGET_PROFILE","slots.* solo esta definido en el perfil hospedado; un perfil de destino no define un allocator de Core");
                            // the resource key is passed as a NUL-terminated constant and compared whole by the runtime
                            const std::string op=e.resolved.substr(15),keyName="@.slotkey."+std::to_string(strings++),keyText=slotCallKey(e.text);
                            globals<<keyName<<" = private unnamed_addr constant ["<<keyText.size()+1<<" x i8] c\"";
                            for(char raw:keyText){ const auto c=static_cast<unsigned char>(raw); globals<<"\\"<<std::uppercase<<std::hex<<std::setw(2)<<std::setfill('0')<<static_cast<unsigned>(c); }
                            globals<<"\\00"<<std::dec<<"\"\n";
                            auto result=[&](const std::string& ok,const std::string& okTy,const std::string& okVal,const std::string& errTy,const std::string& errVal){
                                auto r0=reg(),r1=reg(),r2=reg();
                                emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0"); emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", "+okTy+" "+okVal+", 1"); emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", "+errTy+" "+errVal+", 2");
                                return r2;
                            };
                            auto isZero=[&](const std::string& code){ auto ok=reg(); emit(ok+" = icmp eq i32 "+code+", 0"); return ok; };
                            if(op=="alloc") {
                                lateDecls.insert("declare i32 @omni_slots_alloc(ptr, i32, ptr)");
                                auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_slots_alloc(ptr "+keyName+", i32 "+av[0]+", ptr "+outp+")"); auto hv=reg(); emit(hv+" = load i64, ptr "+outp);
                                return result(isZero(er),"i64",hv,"i32",er);
                            }
                            if(op=="len"||op=="count") { lateDecls.insert("declare i32 @omni_slots_"+op+"(i64)"); auto r=reg(); emit(r+" = call i32 @omni_slots_"+op+"(i64 "+av[0]+")"); return r; }
                            if(op=="gen") { lateDecls.insert("declare i32 @omni_slots_gen(i64, ptr, i32)"); auto r=reg(); emit(r+" = call i32 @omni_slots_gen(i64 "+av[0]+", ptr "+keyName+", i32 "+av[1]+")"); return r; }
                            if(op=="state") { lateDecls.insert("declare i32 @omni_slots_state(i64, ptr, i32)"); auto r=reg(); emit(r+" = call i32 @omni_slots_state(i64 "+av[0]+", ptr "+keyName+", i32 "+av[1]+")"); return r; }
                            if(op=="put") {
                                lateDecls.insert("declare i32 @omni_slots_put(i64, ptr, i32, i64)");
                                auto er=reg(); emit(er+" = call i32 @omni_slots_put(i64 "+av[0]+", ptr "+keyName+", i32 "+av[1]+", i64 "+av[2]+")");
                                return result(isZero(er),"i32",av[1],"i64",av[2]);   // refused: the same handle goes back to the caller as the error
                            }
                            if(op=="take") {
                                lateDecls.insert("declare i32 @omni_slots_take(i64, ptr, i32, ptr)");
                                auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_slots_take(i64 "+av[0]+", ptr "+keyName+", i32 "+av[1]+", ptr "+outp+")"); auto hv=reg(); emit(hv+" = load i64, ptr "+outp);
                                return result(isZero(er),"i64",hv,"i32",er);
                            }
                            if(op=="borrow"||op=="borrow_mut") { lateDecls.insert("declare i64 @omni_slots_borrow(i64, ptr, i32)"); auto r=reg(); emit(r+" = call i64 @omni_slots_borrow(i64 "+av[0]+", ptr "+keyName+", i32 "+av[1]+")"); return r; }
                            if(op=="grow") {
                                lateDecls.insert("declare i32 @omni_slots_grow(i64, i32, ptr)");
                                auto outp=reg(); hoist(outp,"i32"); emit("store i32 0, ptr "+outp); auto er=reg(); emit(er+" = call i32 @omni_slots_grow(i64 "+av[0]+", i32 "+av[1]+", ptr "+outp+")"); auto bv=reg(); emit(bv+" = load i32, ptr "+outp);
                                return result(isZero(er),"i32",bv,"i32",er);
                            }
                            if(op=="release") {
                                lateDecls.insert("declare i32 @omni_slots_release(i64)");
                                auto er=reg(); emit(er+" = call i32 @omni_slots_release(i64 "+av[0]+")");
                                return result(isZero(er),"i32","0","i64",av[0]);   // refused: the buffer itself is the error, handed back to the caller
                            }
                            fail("E_INTERNAL","primitiva de slots sin lowering: "+e.text);
                        }
                        if(e.resolved=="@builtin:resource.seal") { auto r=reg(); emit(r+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 0"); return r; }
                        if(e.resolved=="@builtin:resource.seal_buffer") { auto r=reg(); emit(r+" = extractvalue "+lt(e.args[0].type)+" "+av[0]+", 0"); return r; }
                        if(e.resolved=="@builtin:resource.unseal_buffer") { auto r=reg(); emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i64 "+av[0]+", 0"); return r; }
                        if(e.resolved=="@builtin:resource.inner"||e.resolved=="@builtin:resource.inner_mut") return av[0];
                        if(e.resolved=="@builtin:resource.unseal"||e.resolved=="@builtin:resource.peek") { auto r=reg(); emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i64 "+av[0]+", 0"); return r; }
                        if(e.resolved=="@builtin:buffer.release") { auto r=reg(); emit(r+" = call i32 @omni_buffer_release(i64 "+av[0]+")"); return r; }
                        if(e.resolved=="@builtin:char.from_u32") {
                            auto outp=reg(); hoist(outp,"i32"); emit("store i32 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_char_from_u32(i32 "+av[0]+", ptr "+outp+")");
                            auto cp=reg(); emit(cp+" = load i32, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+cp+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:char.codepoint") return av[0];
                        if(e.resolved=="@builtin:text.from_char") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_text_from_char(i32 "+av[0]+", ptr "+outp+")");
                            auto tv=reg(); emit(tv+" = load i64, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+tv+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:text.equals") {
                            auto eq=reg(); emit(eq+" = call i32 @omni_text_equal(i64 "+av[0]+", i64 "+av[1]+")");
                            auto bit=reg(); emit(bit+" = icmp ne i32 "+eq+", 0"); return bit;
                        }
                        if(e.resolved=="@builtin:text.byte_len") {
                            auto r=reg(); emit(r+" = call i32 @omni_text_byte_len(i64 "+av[0]+")"); return r;
                        }
                        if(e.resolved=="@builtin:text.scalar_len") {
                            auto r=reg(); emit(r+" = call i32 @omni_text_scalar_len(i64 "+av[0]+")"); return r;
                        }
                        if(e.resolved=="@builtin:text.scalar_at") {
                            auto outp=reg(); hoist(outp,"i32"); emit("store i32 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_text_scalar_at(i64 "+av[0]+", i32 "+av[1]+", ptr "+outp+")");
                            auto cp=reg(); emit(cp+" = load i32, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+cp+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:text.len") {
                            auto r=reg(); emit(r+" = call i32 @omni_text_len(i64 "+av[0]+")"); return r;
                        }
                        if(e.resolved=="@builtin:text.concat") {
                            auto r=reg(); emit(r+" = call i64 @omni_text_concat(i64 "+av[0]+", i64 "+av[1]+")"); return r;
                        }
                        if(e.resolved=="@builtin:host.read") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_host_read(i64 "+av[0]+", i32 "+av[1]+", ptr "+outp+")");
                            auto bv=reg(); emit(bv+" = load i64, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+bv+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:host.write") {
                            auto outp=reg(); hoist(outp,"i32"); emit("store i32 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_host_write(i64 "+av[0]+", i64 "+av[1]+", ptr "+outp+")");
                            auto count=reg(); emit(count+" = load i32, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+count+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:host.process") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_host_process(i64 "+av[0]+", i64 "+av[1]+", i32 "+av[2]+", i32 "+av[3]+", ptr "+outp+")");
                            auto bv=reg(); emit(bv+" = load i64, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+bv+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:host.tcp") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_host_tcp(i64 "+av[0]+", i64 "+av[1]+", i32 "+av[2]+", i32 "+av[3]+", ptr "+outp+")");
                            auto bv=reg(); emit(bv+" = load i64, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+bv+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:host.ffi") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_host_ffi(i64 "+av[0]+", i64 "+av[1]+", i32 "+av[2]+", ptr "+outp+")");
                            auto bv=reg(); emit(bv+" = load i64, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+bv+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:file.read_text") {
                            auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                            auto er=reg(); emit(er+" = call i32 @omni_file_read_text(i64 "+av[0]+", ptr "+outp+")");
                            auto tv=reg(); emit(tv+" = load i64, ptr "+outp);
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i64 "+tv+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        if(e.resolved=="@builtin:file.write_text") {
                            auto er=reg(); emit(er+" = call i32 @omni_file_write_text(i64 "+av[0]+", i64 "+av[1]+")");
                            auto len=reg(); emit(len+" = call i32 @omni_text_len(i64 "+av[1]+")");
                            auto ok=reg(); emit(ok+" = icmp eq i32 "+er+", 0");
                            auto r0=reg(),r1=reg(),r2=reg();
                            emit(r0+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                            emit(r1+" = insertvalue "+lt(e.type)+" "+r0+", i32 "+len+", 1");
                            emit(r2+" = insertvalue "+lt(e.type)+" "+r1+", i32 "+er+", 2");
                            return r2;
                        }
                        std::string args;
                        for(size_t i=0; i<e.args.size(); i++) { if(i)args+=", "; args+=lt(e.args[i].type)+" "+av[i]; }
                        auto r=reg();
                        emit(r+" = call "+lt(e.type)+" @omni.fn."+e.resolved+"("+args+")");
                        return r;
                    }
                    case Expr::ClosureCall: {
                        std::string args;
                        bool first=true;
                        for(size_t i=0;i<e.closureCaptureBindings.size();++i) {
                            const auto binding=e.closureCaptureBindings[i];
                            auto r=reg(); auto ty=lt(fn->locals.at(static_cast<size_t>(binding)));
                            emit(r+" = load "+ty+", ptr %v"+std::to_string(binding));
                            if(!first)args+=", ";
                            first=false;
                            args+=ty+" "+r;
                        }
                        for(const auto& a:e.args) {
                            auto v=expr(a);
                            if(!first)args+=", ";
                            first=false;
                            args+=lt(a.type)+" "+v;
                        }
                        auto r=reg();
                        emit(r+" = call "+lt(e.type)+" @omni.fn."+e.resolved+"("+args+")");
                        return r;
                    }
                    case Expr::RecordInit:  {
                        std::string acc="zeroinitializer";
                        for(size_t i=0; i<e.args.size(); i++) {
                            auto v=expr(e.args[i]);
                            auto r=reg();
                            emit(r+" = insertvalue "+lt(e.type)+" "+acc+", "+lt(e.args[i].type)+" "+v+", "+std::to_string(e.indices[i]));
                            acc=r;
                        }
                        return acc;
                    }
                    case Expr::Variant: {
                        std::string acc="zeroinitializer";
                        auto r0=reg(); emit(r0+" = insertvalue "+lt(e.type)+" "+acc+", i8 "+std::to_string(e.binding)+", 0"); acc=r0;
                        if(!e.args.empty()){ auto pv=expr(e.args[0]); auto r=reg(); emit(r+" = insertvalue "+lt(e.type)+" "+acc+", "+lt(e.args[0].type)+" "+pv+", "+std::to_string(e.indices.at(0))); acc=r; }
                        return acc;
                    }
                    case Expr::Field:  {
                        auto a=expr(e.args[0]);
                        auto r=reg();
                        emit(r+" = extractvalue "+lt(e.args[0].type)+" "+a+", "+std::to_string(e.binding));
                        return r;
                    }
                    case Expr::Ok:case Expr::Err:  {
                        auto a=expr(e.args[0]); auto r=reg(),v=reg();
                        emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+(e.kind==Expr::Ok?"true":"false")+", 0");
                        emit(v+" = insertvalue "+lt(e.type)+" "+r+", "+lt(e.args[0].type)+" "+a+", "+(e.kind==Expr::Ok?"1":"2")); return v;
                    }
                    case Expr::Some: { auto a=expr(e.args[0]); auto r=reg(),v=reg(); emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 true, 0"); emit(v+" = insertvalue "+lt(e.type)+" "+r+", "+lt(e.args[0].type)+" "+a+", 1"); return v; }
                    case Expr::None: { auto r=reg(); emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 false, 0"); return r; }
                    case Expr::Join: {
                        auto child=reg(); auto childType=e.type.parts.at(0);
                        emit(child+" = load "+lt(childType)+", ptr %v"+std::to_string(e.binding));
                        auto r=reg(),v=reg();
                        emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 true, 0");
                        emit(v+" = insertvalue "+lt(e.type)+" "+r+", "+lt(childType)+" "+child+", 1");
                        return v;
                    }
                    case Expr::Cancel: {
                        auto r=reg(),v=reg();
                        emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 true, 0");
                        emit(v+" = insertvalue "+lt(e.type)+" "+r+", i32 1, 1");
                        return v;
                    }
                    case Expr::Deadline: {
                        auto ticks=expr(e.args.at(0)),positive=reg(); emit(positive+" = icmp ne i32 "+ticks+", 0");
                        auto childType=e.type.parts.at(0); auto child=reg(); emit(child+" = load "+lt(childType)+", ptr %v"+std::to_string(e.binding));
                        auto r=reg(),ok=reg(),last=reg(); emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+positive+", 0"); emit(ok+" = insertvalue "+lt(e.type)+" "+r+", "+lt(childType)+" "+child+", 1"); emit(last+" = insertvalue "+lt(e.type)+" "+ok+", i32 4, 2"); return last;
                    }
                    case Expr::Channel: {
                        auto capacity=expr(e.args.at(0)),r=reg();
                        emit(r+" = call i64 @omni_channel_new(i32 "+capacity+")"); return r;
                    }
                    case Expr::Send: {
                        auto value=expr(e.args.at(0)),handle=reg();
                        emit(handle+" = load i64, ptr %v"+std::to_string(e.binding));
                        std::string wide=value; auto valueType=e.args.at(0).type;
                        if(isInteger(valueType)&&integerWidth(valueType)<64){ auto cast=reg(); emit(cast+" = zext "+lt(valueType)+" "+value+" to i64"); wide=cast; }
                        auto code=reg(); emit(code+" = call i32 @omni_channel_send(i64 "+handle+", i64 "+wide+")");
                        auto ok=reg(); emit(ok+" = icmp eq i32 "+code+", 0"); auto r=reg(),v=reg(),last=reg();
                        emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+ok+", 0");
                        emit(v+" = insertvalue "+lt(e.type)+" "+r+", i32 0, 1"); emit(last+" = insertvalue "+lt(e.type)+" "+v+", i32 "+code+", 2"); return last;
                    }
                    case Expr::Receive: {
                        auto handle=reg(); emit(handle+" = load i64, ptr %v"+std::to_string(e.binding));
                        auto outp=reg(); hoist(outp,"i64"); emit("store i64 0, ptr "+outp);
                        auto code=reg(); emit(code+" = call i32 @omni_channel_receive(i64 "+handle+", ptr "+outp+")"); auto raw=reg(); emit(raw+" = load i64, ptr "+outp);
                        auto optionType=e.type.parts.at(0); auto element=optionType.parts.at(0); std::string value=raw;
                        if(isInteger(element)&&integerWidth(element)<64){auto narrow=reg();emit(narrow+" = trunc i64 "+raw+" to "+lt(element));value=narrow;}
                        auto has=reg();emit(has+" = icmp eq i32 "+code+", 0");auto closed=reg();emit(closed+" = icmp eq i32 "+code+", 1");
                        auto option0=reg(),option1=reg();emit(option0+" = insertvalue "+lt(optionType)+" zeroinitializer, i1 "+has+", 0");emit(option1+" = insertvalue "+lt(optionType)+" "+option0+", "+lt(element)+" "+value+", 1");
                        auto good=reg(); emit(good+" = or i1 "+has+", "+closed);
                        auto r=reg(),v=reg(),last=reg();
                        emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 "+good+", 0");
                        emit(v+" = insertvalue "+lt(e.type)+" "+r+", "+lt(optionType)+" "+option1+", 1");
                        emit(last+" = insertvalue "+lt(e.type)+" "+v+", i32 "+code+", 2");
                        return last;
                    }
                    case Expr::Try: fail("E_INTERNAL","? sin bajar antes del lowering",e.loc);
                    case Expr::Close: {
                        auto handle=reg();emit(handle+" = load i64, ptr %v"+std::to_string(e.binding));auto code=reg();emit(code+" = call i32 @omni_channel_close(i64 "+handle+")");auto r=reg(),v=reg(),last=reg();emit(r+" = insertvalue "+lt(e.type)+" zeroinitializer, i1 true, 0");emit(v+" = insertvalue "+lt(e.type)+" "+r+", i32 0, 1");emit(last+" = insertvalue "+lt(e.type)+" "+v+", i32 "+code+", 2");return last;
                    }
                    case Expr::Unary:  {
                        if(e.text=="!") { auto a=expr(e.args[0]); auto r=reg(); emit(r+" = xor i1 "+a+", true"); return r; }
                        if(e.text=="-") {
                            auto a=expr(e.args[0]);
                            if(isFloat(e.type)){ auto r=reg(); emit(r+" = fneg "+lt(e.type)+" "+a); return r; }
                            if(e.args[0].kind==Expr::Number){ auto r=reg(); emit(r+" = sub "+lt(e.type)+" 0, "+std::to_string(e.args[0].value)); return r; }
                            auto r=reg(); emit(r+" = call "+lt(e.type)+" @omni_"+typeName(e.type)+"_sub("+lt(e.type)+" 0, "+lt(e.type)+" "+a+")"); return r;
                        }
                        fail("E_INTERNAL","unario sin lowering");
                    }
                    case Expr::Binary:  {
                        auto a=expr(e.args[0]);
                        if(e.text=="&&"||e.text=="||")  {
                            auto left=current,right=lab(),done=lab();
                            bool isAnd=e.text=="&&";
                            emit("br i1 "+a+", label %"+(isAnd?right:done)+", label %"+(isAnd?done:right));
                            mark(right);
                            auto b=expr(e.args[1]);
                            auto rend=current;
                            emit("br label %"+done);
                            mark(done);
                            auto r=reg();
                            emit(r+" = phi i1 [ "+(isAnd?"false":"true")+", %"+left+" ], [ "+b+", %"+rend+" ]");
                            return r;
                        }
                        auto b=expr(e.args[1]);
                        auto r=reg(); auto t=e.args[0].type; auto ty=lt(t); auto tn=typeName(t);
                        if(isFloat(t)){
                            if(e.text=="+"||e.text=="-"||e.text=="*"||e.text=="/"){
                                std::map<std::string,std::string> op={{"+","fadd"},{"-","fsub"},{"*","fmul"},{"/","fdiv"}};
                                if(sse2())return constrainedBinary(op.at(e.text),ty,a,b);
                                emit(r+" = "+op.at(e.text)+" "+ty+" "+a+", "+b);
                            } else {
                                std::map<std::string,std::string> pred={{"==","oeq"},{"!=","une"},{"<","olt"},{"<=","ole"},{">","ogt"},{">=","oge"}};
                                emit(r+" = fcmp "+pred.at(e.text)+" "+ty+" "+a+", "+b);
                            }
                            return r;
                        }
                        if(e.text=="+%"||e.text=="-%"||e.text=="*%") {
                            std::string op=e.text.substr(0,1)=="+"?"add":(e.text.substr(0,1)=="-"?"sub":"mul"); emit(r+" = "+op+" "+ty+" "+a+", "+b);
                        }
                        else if(e.text=="+|"||e.text=="-|"||e.text=="*|") {
                            std::string op=e.text.substr(0,1)=="+"?"add":(e.text.substr(0,1)=="-"?"sub":"mul"); emit(r+" = call "+ty+" @omni_"+tn+"_sat_"+op+"("+ty+" "+a+", "+ty+" "+b+")");
                        }
                        else if(e.text=="+"||e.text=="-"||e.text=="*"||e.text=="/"||e.text=="%")  {
                            std::map<std::string,std::string> names={{"+","add"},{"-","sub"},{"*","mul"},{"/","div"},{"%","rem"}};
                            emit(r+" = call "+ty+" @omni_"+tn+"_"+names.at(e.text)+"("+ty+" "+a+", "+ty+" "+b+")");
                        }
                        else  {
                            const bool sg=isSignedInteger(t);
                            std::map<std::string,std::string> pred={{"==","eq"},{"!=","ne"},{"<",sg?"slt":"ult"},{"<=",sg?"sle":"ule"},{">",sg?"sgt":"ugt"},{">=",sg?"sge":"uge"}};
                            emit(r+" = icmp "+pred.at(e.text)+" "+lt(e.args[0].type)+" "+a+", "+b);
                        }
                        return r;
                    }
                }
                fail("E_INTERNAL","expresion sin lowering");
            }
            bool block(const std::vector<Stmt>& b,const std::vector<int>& extraBindings={})  {
                cleanupScopes.push_back(scopeBindings(b,extraBindings));
                bool term=false;
                for(auto& s:b)  {
                    tick();
                    switch(s.kind)  {
                        case Stmt::Let:case Stmt::Var:case Stmt::Assign:  {
                            auto v=expr(s.expr);
                            emit("store "+lt(s.expr.type)+" "+v+", ptr %v"+std::to_string(s.binding));
                            break;
                        }
                        case Stmt::Destructure: {
                            auto v=expr(s.expr);
                            for(size_t i=0;i<s.bindings.size();++i)if(s.bindings[i]>=0){
                                auto part=reg();
                                emit(part+" = extractvalue "+lt(s.expr.type)+" "+v+", "+std::to_string(i));
                                auto bt=lt(fn->locals.at(static_cast<size_t>(s.bindings[i])));
                                emit("store "+bt+" "+part+", ptr %v"+std::to_string(s.bindings[i]));
                            }
                            break;
                        }
                        case Stmt::TaskScope: { term=block(s.body); break; }
                        case Stmt::Spawn: {
                            auto v=expr(s.expr);
                            auto childType=fn->locals.at(static_cast<size_t>(s.binding)).parts.at(0);
                            emit("store "+lt(childType)+" "+v+", ptr %v"+std::to_string(s.binding));
                            break;
                        }
                        case Stmt::Break: {
                            if(loopTargets.empty())fail("E_INTERNAL","break sin target LLVM");
                            cleanupFrom(loopTargets.back().cleanupDepth);
                            emit("br label %"+loopTargets.back().breakTarget);
                            term=true;
                            break;
                        }
                        case Stmt::Continue: {
                            if(loopTargets.empty())fail("E_INTERNAL","continue sin target LLVM");
                            cleanupFrom(loopTargets.back().cleanupDepth);
                            emit("br label %"+loopTargets.back().continueTarget);
                            term=true;
                            break;
                        }
                        case Stmt::Return:  {
                            auto v=expr(s.expr);
                            cleanupFrom(0);
                            if(!svcFn)emit("call void @omni_leave()");
                            emit("ret "+lt(s.expr.type)+" "+v);
                            term=true;
                            break;
                        }
                        case Stmt::Print:  {
                            auto v=expr(s.expr);
                            if(s.expr.type==Type::Bool)  {
                                auto ext=reg();
                                emit(ext+" = zext i1 "+v+" to i32");
                                emit("call void @omni_print_bool(i32 "+ext+")");
                            }
                            else if(s.expr.type==Type::Text) emit("call void @omni_print_dyn_text(i64 "+v+")");
                            else if(s.expr.type==Type::Char) emit("call void @omni_print_char(i32 "+v+")");
                            else if(s.expr.type.kind==Type::F32||s.expr.type.kind==Type::F64) {
                                if(prof)fail("E_TARGET_PROFILE","imprimir un flotante necesita omni_print_f32/f64, servicios que el contrato del proveedor del perfil no incluye");
                                if(s.expr.type.kind==Type::F32) emit("call void @omni_print_f32(float "+v+")");
                                else emit("call void @omni_print_f64(double "+v+")");
                            }
                            else if(isInteger(s.expr.type)) {
                                std::string wide=v;
                                if(integerWidth(s.expr.type)<64){ auto x=reg(); emit(x+" = "+std::string(isSignedInteger(s.expr.type)?"sext":"zext")+" "+lt(s.expr.type)+" "+v+" to i64"); wide=x; }
                                emit("call void @omni_print_"+std::string(isSignedInteger(s.expr.type)?"i64":"u64")+"(i64 "+wide+")");
                            }
                            break;
                        }
                        case Stmt::PrintText:  {
                            auto name="@.text."+std::to_string(strings++);
                            globals<<name<<" = private unnamed_addr constant ["<<s.text.size()<<" x i8] c\"";
                            for(char raw:s.text){ const auto c=static_cast<unsigned char>(raw); globals<<"\\"<<std::uppercase<<std::hex<<std::setw(2)<<std::setfill('0')<<static_cast<unsigned>(c); }
                            globals<<std::dec<<"\"\n";
                            emit("call void @omni_print_text(ptr "+name+", i32 "+std::to_string(s.text.size())+")");
                            break;
                        }
                        case Stmt::Match:  {
                            auto v=expr(s.expr); auto c=reg(); emit(c+" = extractvalue "+lt(s.expr.type)+" "+v+", 0");
                            auto a=lab(),d=lab(),m=lab(); emit("br i1 "+c+", label %"+a+", label %"+d); mark(a);
                            if(s.binding>=0){ auto av=reg(); emit(av+" = extractvalue "+lt(s.expr.type)+" "+v+", 1"); emit("store "+lt(s.expr.type.parts[0])+" "+av+", ptr %v"+std::to_string(s.binding)); }
                            bool ta=block(s.body,{s.binding}); if(!ta)emit("br label %"+m); mark(d);
                            if(s.otherBinding>=0){ auto dv=reg(); emit(dv+" = extractvalue "+lt(s.expr.type)+" "+v+", 2"); emit("store "+lt(s.expr.type.parts[1])+" "+dv+", ptr %v"+std::to_string(s.otherBinding)); }
                            bool td=block(s.other,{s.otherBinding}); if(!td)emit("br label %"+m); term=ta&&td; if(!term)mark(m); break;
                        }
                        case Stmt::MatchOption: {
                            auto v=expr(s.expr); auto c=reg(); emit(c+" = extractvalue "+lt(s.expr.type)+" "+v+", 0");
                            auto a=lab(),d=lab(),m=lab(); emit("br i1 "+c+", label %"+a+", label %"+d); mark(a);
                            if(s.binding>=0){ auto av=reg(); emit(av+" = extractvalue "+lt(s.expr.type)+" "+v+", 1"); emit("store "+lt(s.expr.type.parts[0])+" "+av+", ptr %v"+std::to_string(s.binding)); }
                            bool ta=block(s.body,{s.binding}); if(!ta)emit("br label %"+m); mark(d); bool td=block(s.other); if(!td)emit("br label %"+m); term=ta&&td; if(!term)mark(m); break;
                        }
                        case Stmt::MatchEnum: {
                            auto v=expr(s.expr); auto tagv=reg(); emit(tagv+" = extractvalue "+lt(s.expr.type)+" "+v+", 0");
                            std::vector<std::string> labs; for(size_t ai=0;ai<s.arms.size();++ai)labs.push_back(lab());
                            auto bad=lab(), mergeLab=lab(); std::ostringstream sw; sw<<"switch i8 "<<tagv<<", label %"<<bad<<" [";
                            for(size_t ai=0;ai<s.arms.size();++ai){ sw<<" i8 "<<s.armVariantIndices[ai]<<", label %"<<labs[ai]; } sw<<" ]"; emit(sw.str());
                            bool all=true;
                            for(size_t ai=0;ai<s.arms.size();++ai){ mark(labs[ai]); if(s.armBindings[ai]>=0){ auto pv=reg(); emit(pv+" = extractvalue "+lt(s.expr.type)+" "+v+", "+std::to_string(s.armPayloadFields[ai])); auto bt=lt(fn->locals.at(static_cast<size_t>(s.armBindings[ai]))); emit("store "+bt+" "+pv+", ptr %v"+std::to_string(s.armBindings[ai])); }
                                bool rt=block(s.arms[ai],{s.armBindings[ai]}); all=all&&rt; if(!rt)emit("br label %"+mergeLab); }
                            mark(bad); emit("unreachable"); term=all; if(!term)mark(mergeLab); break;
                        }
                        case Stmt::If:  {
                            auto c=expr(s.expr),a=lab(),d=lab(),m=lab();
                            emit("br i1 "+c+", label %"+a+", label %"+d);
                            mark(a);
                            bool ta=block(s.body);
                            if(!ta)emit("br label %"+m);
                            mark(d);
                            bool td=block(s.other);
                            if(!td)emit("br label %"+m);
                            term=ta&&td;
                            if(!term)mark(m);
                            break;
                        }
                        case Stmt::Loop:  {
                            auto h=lab(),body=lab(),done=lab();
                            emit("br label %"+h);
                            mark(h);
                            auto c=expr(s.expr);
                            emit("br i1 "+c+", label %"+body+", label %"+done);
                            mark(body);
                            loopTargets.push_back({h,done,cleanupScopes.size()});
                            bool bt=block(s.body);
                            loopTargets.pop_back();
                            if(!bt)emit("br label %"+h);
                            mark(done);
                            break;
                        }
                        case Stmt::ForEach: {
                            auto seq=expr(s.expr);
                            if(s.iteratorProtocol==Stmt::IteratorRange){
                                if(s.expr.type.kind!=Type::Range)fail("E_INTERNAL","resolved Range iteration protocol has incompatible type",s.loc);
                                auto h=lab(),body=lab(),nextLab=lab(),done=lab();
                                auto cur=reg(); hoist(cur,"i32");
                                auto startv=reg(); emit(startv+" = extractvalue "+lt(s.expr.type)+" "+seq+", 0");
                                auto endv=reg(); emit(endv+" = extractvalue "+lt(s.expr.type)+" "+seq+", 1");
                                auto incl=reg(); emit(incl+" = extractvalue "+lt(s.expr.type)+" "+seq+", 2");
                                emit("store i32 "+startv+", ptr "+cur);
                                emit("br label %"+h); mark(h);
                                auto iv=reg(); emit(iv+" = load i32, ptr "+cur);
                                auto ltend=reg(); emit(ltend+" = icmp ult i32 "+iv+", "+endv);
                                auto eqend=reg(); emit(eqend+" = icmp eq i32 "+iv+", "+endv);
                                auto ieq=reg(); emit(ieq+" = and i1 "+incl+", "+eqend);
                                auto cond=reg(); emit(cond+" = or i1 "+ltend+", "+ieq);
                                emit("br i1 "+cond+", label %"+body+", label %"+done);
                                mark(body);
                                if(s.binding>=0)emit("store i32 "+iv+", ptr %v"+std::to_string(s.binding));
                                loopTargets.push_back({nextLab,done,cleanupScopes.size()});
                                bool bt=block(s.body,{s.binding});
                                loopTargets.pop_back();
                                if(!bt)emit("br label %"+nextLab);
                                mark(nextLab);
                                auto isLast=reg(); emit(isLast+" = and i1 "+incl+", "+eqend);
                                auto incLab=lab();
                                emit("br i1 "+isLast+", label %"+done+", label %"+incLab);
                                mark(incLab);
                                auto maxed=reg(); emit(maxed+" = icmp eq i32 "+iv+", 4294967295");
                                auto safeInc=lab(); emit("br i1 "+maxed+", label %"+done+", label %"+safeInc);
                                mark(safeInc);
                                auto next=reg(); emit(next+" = add i32 "+iv+", 1");
                                emit("store i32 "+next+", ptr "+cur);
                                emit("br label %"+h);
                                mark(done);
                            } else if(s.iteratorProtocol==Stmt::IteratorArray||s.iteratorProtocol==Stmt::IteratorView) {
                                if((s.iteratorProtocol==Stmt::IteratorArray&&s.expr.type.kind!=Type::Array)||(s.iteratorProtocol==Stmt::IteratorView&&s.expr.type.kind!=Type::View))fail("E_INTERNAL","resolved collection iteration protocol has incompatible type",s.loc);
                                auto h=lab(),body=lab(),nextLab=lab(),done=lab();
                                auto idx=reg(); hoist(idx,"i32"); emit("store i32 0, ptr "+idx);
                                std::string base,len;
                                if(s.expr.type.kind==Type::Array){
                                    auto slot=reg(); hoist(slot,lt(s.expr.type)); emit("store "+lt(s.expr.type)+" "+seq+", ptr "+slot);
                                    base=reg(); emit(base+" = getelementptr "+lt(s.expr.type)+", ptr "+slot+", i32 0, i32 0");
                                    len=std::to_string(s.expr.type.extent);
                                } else {
                                    base=reg(); emit(base+" = extractvalue "+lt(s.expr.type)+" "+seq+", 0");
                                    len=reg(); emit(len+" = extractvalue "+lt(s.expr.type)+" "+seq+", 1");
                                }
                                emit("br label %"+h); mark(h);
                                auto iv=reg(); emit(iv+" = load i32, ptr "+idx); auto cond=reg(); emit(cond+" = icmp ult i32 "+iv+", "+len);
                                emit("br i1 "+cond+", label %"+body+", label %"+done); mark(body);
                                if(s.binding>=0){
                                    auto ep=reg(); emit(ep+" = getelementptr "+lt(fn->locals.at(static_cast<size_t>(s.binding)))+", ptr "+base+", i32 "+iv);
                                    auto ev=reg(); emit(ev+" = load "+lt(fn->locals.at(static_cast<size_t>(s.binding)))+", ptr "+ep);
                                    emit("store "+lt(fn->locals.at(static_cast<size_t>(s.binding)))+" "+ev+", ptr %v"+std::to_string(s.binding));
                                }
                                loopTargets.push_back({nextLab,done,cleanupScopes.size()});
                                bool bt=block(s.body,{s.binding});
                                loopTargets.pop_back();
                                if(!bt)emit("br label %"+nextLab);
                                mark(nextLab);
                                auto iv2=reg(); emit(iv2+" = load i32, ptr "+idx);
                                auto next=reg(); emit(next+" = add i32 "+iv2+", 1"); emit("store i32 "+next+", ptr "+idx); emit("br label %"+h);
                                mark(done);
                            } else fail("E_INTERNAL","unresolved static iteration protocol",s.loc);
                            break;
                        }
                    }
                    if(term)break;
                }
                if(!term)cleanupFrom(cleanupScopes.size()-1);
                cleanupScopes.pop_back();
                return term;
            }
            // ---- BAREMETAL-001 profile support ----
            // Service contract: Omni function name in the provider module -> (adapter symbol).
            static const std::vector<std::string>& profileSymbols() {
                static const std::vector<std::string> v={"omni_fault","omni_trap_bounds","omni_tooling_visit","omni_tick","omni_enter","omni_leave",
                    "omni_buffer_alloc","omni_buffer_len","omni_buffer_release","omni_buffer_read_u8","omni_buffer_read_u32le","omni_buffer_read_u64le",
                    "omni_buffer_write_u8","omni_buffer_write_u32le","omni_buffer_write_u64le","omni_print_u32","omni_print_u64","omni_cast_int"};
                return v;
            }
            bool profileDefines(const std::string& sym) const {
                for(const auto& x:profileSymbols()) {
                    if(x==sym) {
                        if(!prof->provider&&sym!="omni_fault"&&sym!="omni_trap_bounds"&&sym!="omni_tooling_visit")return false;
                        return true;
                    }
                }
                static const char* tn[]={"u8","u16","u32","u64","i8","i16","i32","i64"};
                for(const char* t:tn)
                    for(const char* op:{"add","sub","mul","div","rem","sat_add","sat_sub","sat_mul"})
                        if(sym==std::string("omni_")+t+"_"+op)return true;
                return false;
            }
            const Function* providerFn(const std::string& name) const {
                const auto key=prof->serviceModule+"."+name;
                for(const auto& f:p.functions)if(f.key==key)return &f;
                return nullptr;
            }
            void requireProvider(const std::string& name,const std::vector<Type::Kind>& params,Type::Kind result) const {
                const auto* f=providerFn(name);
                if(!f)fail("E_SERVICE_BINDING","proveedor de servicio ausente: "+prof->serviceModule+"."+name);
                bool ok=f->params.size()==params.size()&&f->result.kind==result;
                for(size_t i=0;ok&&i<params.size();++i)ok=f->params[i].type.kind==params[i];
                if(!ok)fail("E_SERVICE_BINDING","firma incorrecta de servicio: "+prof->serviceModule+"."+name);
            }
            std::string profileDefinitions() const {
                std::ostringstream o;
                if(sse2()) {
                    // constrained floating-point intrinsics used by the sse2 lowering (round.dynamic / fpexcept.strict)
                    for(const char* op:{"fadd","fsub","fmul","fdiv"}) {
                        o<<"declare float @llvm.experimental.constrained."<<op<<".f32(float, float, metadata, metadata)\n";
                        o<<"declare double @llvm.experimental.constrained."<<op<<".f64(double, double, metadata, metadata)\n";
                    }
                    for(const char* conv:{"sitofp","uitofp"})
                        for(const char* w:{"8","16","32","64"}) {
                            o<<"declare float @llvm.experimental.constrained."<<conv<<".f32.i"<<w<<"(i"<<w<<", metadata, metadata)\n";
                            o<<"declare double @llvm.experimental.constrained."<<conv<<".f64.i"<<w<<"(i"<<w<<", metadata, metadata)\n";
                        }
                    o<<"declare float @llvm.experimental.constrained.fptrunc.f32.f64(double, metadata, metadata)\n";
                }
                struct W{const char* n;int w;bool s;};
                const W ws[]={{"u8",8,false},{"u16",16,false},{"u32",32,false},{"u64",64,false},{"i8",8,true},{"i16",16,true},{"i32",32,true},{"i64",64,true}};
                for(const auto& t:ws) {
                    const std::string ty="i"+std::to_string(t.w), sg=t.s?"s":"u";
                    for(const char* op:{"add","sub","mul"}) {
                        const std::string in="llvm."+sg+op+".with.overflow."+ty;
                        o<<"declare {"<<ty<<", i1} @"<<in<<"("<<ty<<", "<<ty<<")\n";
                    }
                    for(const char* op:{"add","sub"})o<<"declare "<<ty<<" @llvm."<<sg<<op<<".sat."<<ty<<"("<<ty<<", "<<ty<<")\n";
                    for(const char* op:{"add","sub","mul"}) {
                        o<<"define internal "<<ty<<" @omni_"<<t.n<<"_"<<op<<"("<<ty<<" %a, "<<ty<<" %b) {\nentry:\n"
                         <<"  %r = call {"<<ty<<", i1} @llvm."<<sg<<op<<".with.overflow."<<ty<<"("<<ty<<" %a, "<<ty<<" %b)\n"
                         <<"  %v = extractvalue {"<<ty<<", i1} %r, 0\n  %o = extractvalue {"<<ty<<", i1} %r, 1\n"
                         <<"  br i1 %o, label %trap, label %ok\ntrap:\n  call void @omni_fault(i32 2)\n  unreachable\nok:\n  ret "<<ty<<" %v\n}\n";
                    }
                    for(const char* op:{"div","rem"}) {
                        const char* inst=t.s?(std::string(op)=="div"?"sdiv":"srem"):(std::string(op)=="div"?"udiv":"urem");
                        o<<"define internal "<<ty<<" @omni_"<<t.n<<"_"<<op<<"("<<ty<<" %a, "<<ty<<" %b) {\nentry:\n"
                         <<"  %z = icmp eq "<<ty<<" %b, 0\n  br i1 %z, label %dz, label %chk\ndz:\n  call void @omni_fault(i32 3)\n  unreachable\nchk:\n";
                        if(t.s) {
                            const std::string minv=std::string("-")+(t.w==8?"128":t.w==16?"32768":t.w==32?"2147483648":"9223372036854775808");
                            o<<"  %m = icmp eq "<<ty<<" %a, "<<minv<<"\n  %n = icmp eq "<<ty<<" %b, -1\n  %ov = and i1 %m, %n\n"
                             <<"  br i1 %ov, label %of, label %ok\nof:\n  call void @omni_fault(i32 2)\n  unreachable\nok:\n";
                        } else o<<"  br label %ok\nok:\n";
                        o<<"  %r = "<<inst<<" "<<ty<<" %a, %b\n  ret "<<ty<<" %r\n}\n";
                    }
                    for(const char* op:{"add","sub"})
                        o<<"define internal "<<ty<<" @omni_"<<t.n<<"_sat_"<<op<<"("<<ty<<" %a, "<<ty<<" %b) {\nentry:\n  %r = call "<<ty<<" @llvm."<<sg<<op<<".sat."<<ty<<"("<<ty<<" %a, "<<ty<<" %b)\n  ret "<<ty<<" %r\n}\n";
                    {
                        const std::string maxv=t.s?(t.w==8?"127":t.w==16?"32767":t.w==32?"2147483647":"9223372036854775807"):"-1";
                        const std::string minv=t.s?(t.w==8?"-128":t.w==16?"-32768":t.w==32?"-2147483648":"-9223372036854775808"):"0";
                        o<<"define internal "<<ty<<" @omni_"<<t.n<<"_sat_mul("<<ty<<" %a, "<<ty<<" %b) {\nentry:\n"
                         <<"  %r = call {"<<ty<<", i1} @llvm."<<sg<<"mul.with.overflow."<<ty<<"("<<ty<<" %a, "<<ty<<" %b)\n"
                         <<"  %v = extractvalue {"<<ty<<", i1} %r, 0\n  %o = extractvalue {"<<ty<<", i1} %r, 1\n";
                        if(t.s)
                            o<<"  %an = icmp slt "<<ty<<" %a, 0\n  %bn = icmp slt "<<ty<<" %b, 0\n  %same = icmp eq i1 %an, %bn\n  %sat = select i1 %same, "<<ty<<" "<<maxv<<", "<<ty<<" "<<minv<<"\n";
                        else o<<"  %sat = select i1 true, "<<ty<<" "<<maxv<<", "<<ty<<" 0\n";
                        o<<"  %out = select i1 %o, "<<ty<<" %sat, "<<ty<<" %v\n  ret "<<ty<<" %out\n}\n";
                    }
                }
                // fault: bound to the provider's trap, or a halt loop without a provider.
                o<<"define internal void @omni_fault(i32 %code) noreturn {\nentry:\n";
                if(prof->provider)o<<"  %r = call i32 @omni.fn."<<prof->serviceModule<<".trap(i32 %code)\n  br label %halt\n";
                else o<<"  br label %halt\n";
                o<<"halt:\n  call void asm sideeffect \"cli; hlt\", \"~{memory}\"()\n  br label %halt\n}\n";
                o<<"define internal void @omni_trap_bounds() {\nentry:\n  call void @omni_fault(i32 1)\n  unreachable\n}\n";
                o<<"define internal void @omni_tooling_visit(i64 %id) {\nentry:\n  ret void\n}\n";
                if(!prof->provider)return o.str();
                const std::string m="@omni.fn."+prof->serviceModule+".";
                o<<"define internal void @omni_tick() {\nentry:\n  %r = call i32 "<<m<<"tick()\n  ret void\n}\n";
                o<<"define internal void @omni_enter() {\nentry:\n  %r = call i32 "<<m<<"enter()\n  ret void\n}\n";
                o<<"define internal void @omni_leave() {\nentry:\n  %r = call i32 "<<m<<"leave()\n  ret void\n}\n";
                o<<"define internal i32 @omni_buffer_alloc(i32 %n, ptr %out) {\nentry:\n  %s = call i32 "<<m<<"buf_alloc(i32 %n)\n  %h = call i64 "<<m<<"out64()\n  store i64 %h, ptr %out\n  ret i32 %s\n}\n";
                o<<"define internal i32 @omni_buffer_len(i64 %h) {\nentry:\n  %r = call i32 "<<m<<"buf_len(i64 %h)\n  ret i32 %r\n}\n";
                o<<"define internal i32 @omni_buffer_release(i64 %h) {\nentry:\n  %r = call i32 "<<m<<"buf_release(i64 %h)\n  ret i32 %r\n}\n";
                o<<"define internal i32 @omni_buffer_read_u8(i64 %h, i32 %i, ptr %out) {\nentry:\n  %s = call i32 "<<m<<"buf_read8(i64 %h, i32 %i)\n  %v = call i32 "<<m<<"out32()\n  store i32 %v, ptr %out\n  ret i32 %s\n}\n";
                o<<"define internal i32 @omni_buffer_read_u32le(i64 %h, i32 %i, ptr %out) {\nentry:\n  %s = call i32 "<<m<<"buf_read32(i64 %h, i32 %i)\n  %v = call i32 "<<m<<"out32()\n  store i32 %v, ptr %out\n  ret i32 %s\n}\n";
                o<<"define internal i32 @omni_buffer_read_u64le(i64 %h, i32 %i, ptr %out) {\nentry:\n  %s = call i32 "<<m<<"buf_read64(i64 %h, i32 %i)\n  %v = call i64 "<<m<<"out64()\n  store i64 %v, ptr %out\n  ret i32 %s\n}\n";
                o<<"define internal i32 @omni_buffer_write_u8(i64 %h, i32 %i, i32 %v) {\nentry:\n  %r = call i32 "<<m<<"buf_write8(i64 %h, i32 %i, i32 %v)\n  ret i32 %r\n}\n";
                o<<"define internal i32 @omni_buffer_write_u32le(i64 %h, i32 %i, i32 %v) {\nentry:\n  %r = call i32 "<<m<<"buf_write32(i64 %h, i32 %i, i32 %v)\n  ret i32 %r\n}\n";
                o<<"define internal i32 @omni_buffer_write_u64le(i64 %h, i32 %i, i64 %v) {\nentry:\n  %r = call i32 "<<m<<"buf_write64(i64 %h, i32 %i, i64 %v)\n  ret i32 %r\n}\n";
                o<<"define internal void @omni_print_u32(i32 %v) {\nentry:\n  %r = call i32 "<<m<<"print_u32(i32 %v)\n  ret void\n}\n";
                o<<"define internal void @omni_print_u64(i64 %v) {\nentry:\n  %r = call i32 "<<m<<"print_u64(i64 %v)\n  ret void\n}\n";
                o<<"define internal i64 @omni_cast_int(i64 %bits, i32 %sg, i32 %sw, i32 %dg, i32 %dw) {\nentry:\n  %r = call i64 "<<m<<"cast_int(i64 %bits, i32 %sg, i32 %sw, i32 %dg, i32 %dw)\n  ret i64 %r\n}\n";
                return o.str();
            }
            void validateProfile() const {
                if(prof->provider) {
                    using K=Type::Kind;
                    const std::vector<std::pair<const char*,std::pair<std::vector<K>,K>>> req={
                        {"begin",{{},Type::U32}},{"tick",{{},Type::U32}},{"enter",{{},Type::U32}},{"leave",{{},Type::U32}},{"trap",{{Type::U32},Type::U32}},
                        {"buf_alloc",{{Type::U32},Type::U32}},{"buf_len",{{Type::U64},Type::U32}},{"buf_release",{{Type::U64},Type::U32}},
                        {"buf_read8",{{Type::U64,Type::U32},Type::U32}},{"buf_read32",{{Type::U64,Type::U32},Type::U32}},{"buf_read64",{{Type::U64,Type::U32},Type::U32}},
                        {"buf_write8",{{Type::U64,Type::U32,Type::U32},Type::U32}},{"buf_write32",{{Type::U64,Type::U32,Type::U32},Type::U32}},{"buf_write64",{{Type::U64,Type::U32,Type::U64},Type::U32}},
                        {"out32",{{},Type::U32}},{"out64",{{},Type::U64}},{"print_u32",{{Type::U32},Type::U32}},{"print_u64",{{Type::U64},Type::U32}},
                        {"cast_int",{{Type::U64,Type::U32,Type::U32,Type::U32,Type::U32},Type::U64}}};
                    for(const auto& r:req)requireProvider(r.first,r.second.first,r.second.second);
                }
            }
            public:explicit LLVM(const Program& x):p(x)  {
            }
            void setProfile(const TargetProfile* t){prof=t;}
            std::string run(const std::string& hostFunctionKey={})  {
                struct ProfileScope { explicit ProfileScope(const TargetProfile* t){ gLoweringProfile=t; } ~ProfileScope(){ gLoweringProfile=nullptr; } } profileScope(prof);
                if(prof)validateProfile();
                if(!p.threadLocals.empty()&&(!prof||prof->name!="baremetal-x86_64"))fail("E_TARGET_PROFILE","thread_local requiere el perfil baremetal-x86_64");
                out<<"; Omni Core "<<VERSION<<" -- generated LLVM IR\nsource_filename = \"omni-core\"\ntarget triple = \"";
                out<<(prof?prof->triple:std::string("x86_64-unknown-linux-gnu"));
                out<<"\"\n\n";
                std::ostringstream savedOut; savedOut.swap(out);
                out<<"declare void @omni_runtime_begin()\ndeclare void @omni_runtime_configure(i32, ptr)\ndeclare void @omni_runtime_end()\ndeclare void @omni_tooling_visit(i64)\ndeclare void @omni_tick()\ndeclare void @omni_enter()\ndeclare void @omni_leave()\ndeclare void @omni_print_u32(i32)\ndeclare void @omni_print_u64(i64)\ndeclare void @omni_print_i64(i64)\ndeclare void @omni_print_char(i32)\ndeclare void @omni_print_f32(float)\ndeclare void @omni_print_f64(double)\ndeclare void @omni_print_bool(i32)\ndeclare void @omni_print_text(ptr, i32)\ndeclare void @omni_print_dyn_text(i64)\ndeclare i64 @omni_cast_int(i64, i32, i32, i32, i32)\ndeclare i64 @omni_cast_float_to_int(double, i32, i32)\ndeclare i64 @omni_text_new(ptr, i32)\ndeclare i32 @omni_text_len(i64)\ndeclare i32 @omni_text_byte_len(i64)\ndeclare i32 @omni_text_equal(i64, i64)\ndeclare i32 @omni_text_scalar_len(i64)\ndeclare i32 @omni_text_scalar_at(i64, i32, ptr)\ndeclare i32 @omni_text_from_char(i32, ptr)\ndeclare i32 @omni_char_from_u32(i32, ptr)\ndeclare i32 @omni_char_codepoint(i32)\ndeclare i64 @omni_text_concat(i64, i64)\ndeclare i32 @omni_file_read_text(i64, ptr)\ndeclare i32 @omni_file_write_text(i64, i64)\ndeclare i32 @omni_host_read(i64, i32, ptr)\ndeclare i32 @omni_host_write(i64, i64, ptr)\ndeclare i32 @omni_host_process(i64, i64, i32, i32, ptr)\ndeclare i32 @omni_host_tcp(i64, i64, i32, i32, ptr)\ndeclare i32 @omni_host_ffi(i64, i64, i32, ptr)\ndeclare i64 @omni_bytes_from_text(i64)\ndeclare i32 @omni_bytes_len(i64)\ndeclare i64 @omni_bytes_concat(i64, i64)\ndeclare i32 @omni_bytes_to_text(i64, ptr)\ndeclare i32 @omni_buffer_alloc(i32, ptr)\ndeclare i32 @omni_buffer_len(i64)\ndeclare i32 @omni_buffer_write_u8(i64, i32, i32)\ndeclare i32 @omni_buffer_read_u8(i64, i32, ptr)\ndeclare i32 @omni_buffer_read_u32le(i64, i32, ptr)\ndeclare i32 @omni_buffer_read_u64le(i64, i32, ptr)\ndeclare i32 @omni_buffer_write_u32le(i64, i32, i32)\ndeclare i32 @omni_buffer_write_u64le(i64, i32, i64)\ndeclare i32 @omni_buffer_freeze(i64, ptr)\ndeclare i32 @omni_buffer_release(i64)\ndeclare void @omni_trap_bounds()\ndeclare i64 @omni_channel_new(i32)\ndeclare i32 @omni_channel_send(i64, i64)\ndeclare i32 @omni_channel_receive(i64, ptr)\ndeclare i32 @omni_channel_close(i64)\n";
                for(const char* tn:{"u8","u16","u32","u64","i8","i16","i32","i64"}){
                    Type t=parseType(tn); auto ty=lt(t);
                    for(const char* n:{"add","sub","mul","div","rem"})out<<"declare "<<ty<<" @omni_"<<tn<<"_"<<n<<"("<<ty<<", "<<ty<<")\n";
                    for(const char* n:{"add","sub","mul"})out<<"declare "<<ty<<" @omni_"<<tn<<"_sat_"<<n<<"("<<ty<<", "<<ty<<")\n";
                }
                {
                    std::string decls=out.str(); out.swap(savedOut);
                    if(!prof)out<<decls;
                    else {
                        // Symbols this profile defines itself must not stay declared.
                        std::istringstream lines(decls); std::string line;
                        while(std::getline(lines,line)) {
                            if(line.rfind("declare ",0)==0) {
                                const auto at=line.find('@'),par=line.find('(',at);
                                const auto sym=line.substr(at+1,par-at-1);
                                if(profileDefines(sym))continue;
                            }
                            out<<line<<"\n";
                        }
                        out<<profileDefinitions();
                        if(!p.threadLocals.empty()) {
                            auto lay=threadLocalLayout(p); auto ord=orderedThreadLocals(p);
                            std::vector<uint8_t> img(lay.size,0);
                            auto put=[&](uint64_t at,uint64_t v,unsigned w){ for(unsigned i=0;i<w;++i)img[at+i]=static_cast<uint8_t>(v>>(8*i)); };
                            put(0,3554268455816285519ULL,8); put(8,lay.size,8);
                            for(size_t i=0;i<ord.size();++i) { const unsigned w=integerWidth(ord[i]->type)/8; uint64_t v=ord[i]->negative?(~ord[i]->magnitude+1):ord[i]->magnitude; put(lay.offsets[i],v,w); }
                            out<<"@omni.tls.template = internal constant ["<<lay.size<<" x i8] c\"";
                            for(uint8_t b:img) { static const char* hex="0123456789ABCDEF"; out<<"\\"<<hex[b>>4]<<hex[b&15]; }
                            out<<"\"\n";
                        }
                    }
                }
                for(auto& d:p.enums) {
                    out<<"%omni.enum."<<d.key<<" = type { i8";
                    for(auto&v:d.variants)if(v.hasPayload)out<<", "<<lt(v.payload);
                    out<<" }\n";
                }
                for(auto& d:p.records) {
                    out<<"%omni.type."<<d.key<<" = type "<<(d.packed?"<{ ":"{ ");
                    for(size_t i=0; i<d.fields.size(); i++) {
                        if(i)out<<", ";
                        out<<lt(d.fields[i].type);
                    }
                    out<<(d.packed?" }>\n":" }\n");
                }
                if(prof&&prof->pvhNote&&prof->entryStack!=0) {
                    // Naked entry for a CPU state with no usable stack (PVH): two instructions derived from the
                    // declared stack top; everything else is the program's own `main`. Emitted first so that,
                    // in the single entry section, it sits at the section start (the PVH entry address), and the
                    // jump to `main` is resolved by the assembler (same section, local symbol: no relocation).
                    out<<"\ndefine void @omni_boot_entry32() naked noreturn nounwind"<<(prof->entrySection.empty()?"":" section \""+prof->entrySection+"\"")
                       <<" {\nentry:\n  call void asm sideeffect \"movl $$"<<prof->entryStack<<", %esp\\0A"<<(prof->entryHandoffStore?"movl %ebx, "+std::to_string(prof->entryHandoffStore)+"\\0A":"")<<"jmp ${0:c}\", \"i\"(ptr @omni.fn."<<p.module<<".main)\n  unreachable\n}\n";
                }
                if(prof&&!prof->exceptionHandler.empty()) {
                    // 32 fixed-size (16 B) exception stubs + one common tail, in section .text.omni_isr (the linker
                    // script fixes its address). Each stub normalises the frame to [vector][error][rip][cs][rflags][rsp][ss]
                    // and the tail calls the declared handler `(frame u64) u32`, which must not return (cli; hlt if it does).
                    if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","--exception-handler requiere el perfil baremetal-x86_64");
                    bool found=false;
                    for(auto& f:p.functions)if(f.key==prof->exceptionHandler){ found=true; if(f.params.size()!=1||f.params[0].type.kind!=Type::U64||f.result.kind!=Type::U32)fail("E_EXCEPTION_HANDLER","el handler debe ser (u64) u32: "+prof->exceptionHandler); }
                    if(!found)fail("E_EXCEPTION_HANDLER","handler inexistente: "+prof->exceptionHandler);
                    std::ostringstream a;
                    a<<".pushsection .text.omni_isr,\\22ax\\22,@progbits\\0A.balign 16\\0A.globl omni_isr_table\\0Aomni_isr_table:\\0A";
                    for(uint32_t v=0; v<prof->isrCount; v++) {
                        const bool err=v==8||v==10||v==11||v==12||v==13||v==14||v==17||v==21||v==29||v==30;
                        a<<".balign 16\\0A"<<(err?"":"pushq $0\\0A")<<"pushq $"<<v<<"\\0Ajmp omni_isr_common\\0A";
                    }
                    if(prof->isrExtraVector!=0) a<<".balign 16\\0Apushq $0\\0Apushq $"<<prof->isrExtraVector<<"\\0Ajmp omni_isr_common\\0A";
                    if(prof->exceptionResume) {
                        // resumable tail: caller-saved GPRs saved around the handler call; frame pointer (-> vector) in rdi;
                        // handler result 0 = resume: validate the frame, restore, drop [vector][error], iretq. Non-zero = terminal (cli; hlt).
                        // CP-12 row 12.4 (FPU_SSE_STATE_CANDIDATE.md section 10): the frame the handler returns is NEVER trusted. Two qwords saved below the registers hold what the hardware pushed
                        // (CS, RFLAGS); after the handler returns 0 the tail checks the frame it is about to iretq: CS unchanged (bit 0 of the report), RIP canonical (bit 1), RFLAGS with its reserved
                        // bit set, NT clear and IOPL as it entered (bit 2), RSP canonical for an entry from CPL0 and in the lower half for an entry from CPL3 - judged by the CS of the ENTRY, not by the one the handler left (bit 3). A frame that fails is NOT resumed: the handler is called once
                        // more with vector 256 and the report in the error-code slot, and whatever it returns the tail ends in `cli; hlt`.
                        // The two extra qwords keep the stack 16-aligned (eleven pushes) and sit below r11, so the layout the handlers use (rax at frame-8 ...) is unchanged.
                        auto L=[](const std::string& line){ return line+"\\0A"; };
                        // base register %r9 points at [entry RFLAGS][entry CS][r11]...; the frame is at 88(%r9)
                        std::string check;
                        check+=L("lea 88(%r9), %rsi")+L("xorl %edx, %edx");
                        check+=L("movq 24(%rsi), %rax")+L("cmpq 8(%r9), %rax")+L("je 3f")+L("orl $1, %edx")+L("3:");
                        check+=L("movq 16(%rsi), %rax")+L("movq %rax, %rcx")+L("sarq $47, %rcx")+L("addq $1, %rcx")+L("cmpq $1, %rcx")+L("jbe 4f")+L("orl $2, %edx")+L("4:");
                        check+=L("movq 32(%rsi), %rax")+L("movq (%r9), %rcx")+L("xorq %rax, %rcx")+L("testq $0x3000, %rcx")+L("jnz 5f")+L("testq $0x4000, %rax")+L("jnz 5f")
                              +L("testq $2, %rax")+L("jnz 6f")+L("5:")+L("orl $4, %edx")+L("6:");
                        check+=L("movq 40(%rsi), %rax")+L("movl 8(%r9), %ecx")+L("andl $3, %ecx")+L("cmpl $3, %ecx")+L("jne 7f")+L("shrq $47, %rax")+L("jz 8f")+L("orl $8, %edx")+L("jmp 8f")
                              +L("7:")+L("movq %rax, %rcx")+L("sarq $47, %rcx")+L("addq $1, %rcx")+L("cmpq $1, %rcx")+L("jbe 8f")+L("orl $8, %edx")+L("8:");
                        const std::string refuse=L("testl %edx, %edx")+L("jz 9f")+L("movq $256, (%rsi)")+L("movq %rdx, 8(%rsi)")+L("movq %rsi, %rdi")+L("call omni.fn."+prof->exceptionHandler)+L("jmp 2f")+L("9:");
                        const std::string saveRegs=L(".balign 16")+L("omni_isr_common:")+L("push %rax")+L("push %rcx")+L("push %rdx")+L("push %rsi")+L("push %rdi")+L("push %r8")+L("push %r9")
                              +L("push %r10")+L("push %r11")+L("pushq 96(%rsp)")+L("pushq 112(%rsp)");
                        const std::string popRegs=L("addq $16, %rsp")+L("pop %r11")+L("pop %r10")+L("pop %r9")+L("pop %r8")+L("pop %rdi")+L("pop %rsi")+L("pop %rdx")+L("pop %rcx")+L("pop %rax")
                              +L("add $16, %rsp")+L("iretq");
                        if(prof->exceptionSaveFpu) {
                            // --exception-save-fpu: x87/SSE state of the interrupted code is kept in 512 aligned bytes on the interrupted stack
                            // (fxsave64) and restored (fxrstor64) before iretq. The original rsp is stashed just above the image, so the restore
                            // needs no register the handler could have changed. (FPU_SSE_STATE_CANDIDATE.md section 4)
                            a<<saveRegs<<L("cld")<<L("movq %rsp, %rax")<<L("subq $528, %rsp")<<L("andq $-16, %rsp")<<L("movq %rax, 512(%rsp)")<<L("fxsave64 (%rsp)")<<L("leaq 88(%rax), %rdi")
                              <<L("call omni.fn."+prof->exceptionHandler)<<L("testl %eax, %eax")<<L("jnz 2f")
                              <<L("movq 512(%rsp), %r9")<<check<<refuse<<L("fxrstor64 (%rsp)")<<L("movq 512(%rsp), %rsp")<<popRegs
                              <<L("2: cli")<<L("hlt")<<L("jmp 2b")<<".popsection\\0A";
                        } else
                        a<<saveRegs<<L("cld")<<L("leaq 88(%rsp), %rdi")<<L("call omni.fn."+prof->exceptionHandler)<<L("testl %eax, %eax")<<L("jnz 2f")
                          <<L("movq %rsp, %r9")<<check<<refuse<<popRegs
                          <<L("2: cli")<<L("hlt")<<L("jmp 2b")<<".popsection\\0A";
                    } else
                    a<<".balign 16\\0Aomni_isr_common:\\0Acld\\0Amovq %rsp, %rdi\\0Aandq $-16, %rsp\\0Acall omni.fn."<<prof->exceptionHandler<<"\\0Acli\\0A1: hlt\\0Ajmp 1b\\0A.popsection\\0A";
                    out<<"\nmodule asm \""<<a.str()<<"\"\n";
                }
                if(prof&&!prof->threadEntry.empty()) {
                    if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","--thread-entry requiere el perfil baremetal-x86_64");
                    bool tf=false;
                    for(auto& f:p.functions)if(f.key==prof->threadEntry){ tf=true; if(!f.params.empty()||f.result.kind!=Type::U32)fail("E_THREAD_ENTRY","la entrada de hilo debe ser () u32: "+prof->threadEntry); }
                    if(!tf)fail("E_THREAD_ENTRY","entrada de hilo inexistente: "+prof->threadEntry);
                    // switch: save callee-saved + rsp into old area, load from new area, `ret` into the new context (a fresh one has the
                    // trampoline address on top of its stack). trampoline: align, call the entry function, never fall off.
                    out<<"\ndeclare i64 @omni_switch_context(i64, i64)\n@omni_thread_trampoline = external global i8\n";
                    out<<"module asm \".text\\0A.globl omni_switch_context\\0Aomni_switch_context:\\0Amovq %rbx, 0(%rdi)\\0Amovq %rbp, 8(%rdi)\\0Amovq %r12, 16(%rdi)\\0Amovq %r13, 24(%rdi)\\0Amovq %r14, 32(%rdi)\\0Amovq %r15, 40(%rdi)\\0Amovq %rsp, 48(%rdi)\\0A"
                      <<"movq 0(%rsi), %rbx\\0Amovq 8(%rsi), %rbp\\0Amovq 16(%rsi), %r12\\0Amovq 24(%rsi), %r13\\0Amovq 32(%rsi), %r14\\0Amovq 40(%rsi), %r15\\0Amovq 48(%rsi), %rsp\\0Axorl %eax, %eax\\0Aret\\0A"
                      <<".globl omni_thread_trampoline\\0Aomni_thread_trampoline:\\0Aandq $-16, %rsp\\0Acall omni.fn."<<prof->threadEntry<<"\\0Acli\\0A1: hlt\\0Ajmp 1b\\0A\"\n";
                }
                if(prof&&prof->ring3Support) {
                    if(prof->name!="baremetal-x86_64")fail("E_TARGET_PROFILE","--ring3-support requiere el perfil baremetal-x86_64");
                    // enter: save callee-saved + rsp in `area`, build an iretq frame (SS=0x1B, RSP, RFLAGS=2, CS=0x23, RIP) and drop to CPL3 with
                    // every other register cleared. leave: restore them and `ret` to the caller of enter with rax = value (longjmp-like).
                    out<<"\ndeclare i64 @omni_enter_ring3(i64, i64, i64)\ndeclare i64 @omni_leave_ring3(i64, i64)\n";
                    out<<"module asm \".text\\0A.globl omni_enter_ring3\\0Aomni_enter_ring3:\\0Amovq %rbx, 0(%rdx)\\0Amovq %rbp, 8(%rdx)\\0Amovq %r12, 16(%rdx)\\0Amovq %r13, 24(%rdx)\\0Amovq %r14, 32(%rdx)\\0Amovq %r15, 40(%rdx)\\0Amovq %rsp, 48(%rdx)\\0A"
                      <<"pushq $27\\0Apushq %rsi\\0Apushq $2\\0Apushq $35\\0Apushq %rdi\\0Axorl %eax, %eax\\0Axorl %ebx, %ebx\\0Axorl %ecx, %ecx\\0Axorl %edx, %edx\\0Axorl %esi, %esi\\0Axorl %edi, %edi\\0Axorl %ebp, %ebp\\0A"
                      <<"xorl %r8d, %r8d\\0Axorl %r9d, %r9d\\0Axorl %r10d, %r10d\\0Axorl %r11d, %r11d\\0Axorl %r12d, %r12d\\0Axorl %r13d, %r13d\\0Axorl %r14d, %r14d\\0Axorl %r15d, %r15d\\0Airetq\\0A"
                      <<".globl omni_leave_ring3\\0Aomni_leave_ring3:\\0Amovq 0(%rdi), %rbx\\0Amovq 8(%rdi), %rbp\\0Amovq 16(%rdi), %r12\\0Amovq 24(%rdi), %r13\\0Amovq 32(%rdi), %r14\\0Amovq 40(%rdi), %r15\\0Amovq 48(%rdi), %rsp\\0Amovq %rsi, %rax\\0Aret\\0A\"\n";
                }
                size_t functionIndex=0;
                // MN-13: integer arguments of a C boundary carry the extension a C compiler gives them (zeroext/signext on 8- and 16-bit values).
                auto cAbi=[&](const Type& t)->std::string{ return (t.kind==Type::U8||t.kind==Type::U16)?" zeroext":((t.kind==Type::I8||t.kind==Type::I16)?" signext":""); };
                for(auto& f:p.functions)  {
                    fn=&f;
                    temp=0;
                    if(f.isExtern) {
                        if(!prof)fail("E_TARGET_PROFILE","una funcion extern solo existe en un perfil de destino freestanding: "+f.name,f.loc);
                        std::string decl,args,thunk;
                        for(size_t i=0;i<f.params.size();i++) {
                            if(i) { decl+=", "; args+=", "; thunk+=", "; }
                            decl+=lt(f.params[i].type)+cAbi(f.params[i].type); args+=lt(f.params[i].type)+cAbi(f.params[i].type)+" %a"+std::to_string(i); thunk+=lt(f.params[i].type)+" %a"+std::to_string(i);
                        }
                        out<<"\ndeclare"<<cAbi(f.result)<<" "<<lt(f.result)<<" @"<<f.externName<<"("<<decl<<")\n";
                        out<<"\ndefine "<<(prof->pvhNote?"internal ":"")<<lt(f.result)<<" @omni.fn."<<f.key<<"("<<thunk<<") {\nentry:\n  %r = call"<<cAbi(f.result)<<" "<<lt(f.result)<<" @"<<f.externName<<"("<<args<<")\n  ret "<<lt(f.result)<<" %r\n}\n";
                        continue;
                    }
                    label=0;
                    cleanupScopes.clear();
                    hoisted.clear();
                    std::ostringstream outerOut; outerOut.swap(out);
                    out<<"\ndefine "<<(hostFunctionKey.empty()?(prof&&prof->pvhNote?"internal ":""):"hidden ")<<lt(f.result)<<" @omni.fn."<<f.key<<"(";
                    for(size_t i=0; i<f.params.size(); i++)  {
                        if(i)out<<", ";
                        out<<lt(f.params[i].type)<<" %a"<<i;
                    }
                    out<<")"<<(sse2()?" strictfp":"")<<(f.noInline?" noinline":"")<<(!f.section.empty()?" section \""+f.section+"\"":(prof&&prof->pvhNote&&!prof->entrySection.empty()?" section \""+prof->entrySection+"\"":""))<<" {\n";
                    mark("entry");
                    svcFn=prof&&!prof->serviceModule.empty()&&f.module==prof->serviceModule;
                    {
                        const auto visitId=functionIndex++;
                        if(!prof)emit("call void @omni_tooling_visit(i64 "+std::to_string(visitId)+")");
                    }
                    if(!svcFn)emit("call void @omni_enter()");
                    for(size_t i=0; i<f.locals.size(); i++)emit("%v"+std::to_string(i)+" = alloca "+lt(f.locals[i]));
                    out<<"@@OMNI_HOISTED_ALLOCAS@@\n";
                    for(size_t i=0; i<f.params.size(); i++)emit("store "+lt(f.params[i].type)+" %a"+std::to_string(i)+", ptr %v"+std::to_string(f.params[i].binding));
                    std::vector<int> parameters;
                    for(const auto& parameter:f.params)parameters.push_back(parameter.binding);
                    cleanupScopes.push_back(std::move(parameters));
                    if(!block(f.body))fail("E_INTERNAL","funcion sin retorno en lowering");
                    cleanupScopes.pop_back();
                    out<<"}\n";
                    if(!f.exportName.empty()) {
                        // MN-13/16: the C symbol is a thin external wrapper in a section named after it, so a linker script can keep or place every export (KEEP(*(.text.omni_export.*))).
                        std::string params,args;
                        for(size_t i=0;i<f.params.size();i++) {
                            if(i) { params+=", "; args+=", "; }
                            params+=lt(f.params[i].type)+cAbi(f.params[i].type)+" %a"+std::to_string(i); args+=lt(f.params[i].type)+" %a"+std::to_string(i);
                        }
                        out<<"\ndefine"<<cAbi(f.result)<<" "<<lt(f.result)<<" @"<<f.exportName<<"("<<params<<") section \".text.omni_export."<<f.exportName<<"\" {\nentry:\n  %r = call "<<lt(f.result)<<" @omni.fn."<<f.key<<"("<<args<<")\n  ret "<<lt(f.result)<<" %r\n}\n";
                    }
                    {
                        std::string body=out.str(), slots;
                        for(const auto& h:hoisted)slots+=h;
                        const std::string marker="@@OMNI_HOISTED_ALLOCAS@@\n";
                        auto at=body.find(marker);
                        if(at==std::string::npos)fail("E_INTERNAL","hoist marker missing in LLVM lowering");
                        body.replace(at,marker.size(),slots);
                        out.swap(outerOut);
                        out<<body;
                    }
                }
                if(prof) {
                    const std::string entrySym=prof->pvhNote?"omni_boot_entry32":"omni_boot_entry";
                    if(prof->entryStack!=0&&prof->pvhNote) {
                        // entry stub already emitted before the functions
                    } else
                    out<<"\ndefine void @"<<entrySym<<"()"<<(prof->entrySection.empty()?"":" section \""+prof->entrySection+"\"")<<" {\nentry:\n  "<<(prof->provider?"  %b = call i32 @omni.fn."+prof->serviceModule+".begin()\n":"")<<"  %r = call i32 @omni.fn."<<p.module<<".main()\n  call void @omni_fault(i32 9)\n  unreachable\n}\n";
                    if(prof->pvhNote&&prof->entryAddress==0)fail("E_TARGET_PROFILE","pvhNote requiere --entry-address");
                    if(prof->pvhNote)out<<"\n@omni.pvh.note = constant { i32, i32, i32, [4 x i8], i32 } { i32 4, i32 4, i32 18, [4 x i8] c\"Xen\\00\", i32 "<<prof->entryAddress<<" }, section \".note.pvh\", align 4\n";
                } else
                if(hostFunctionKey.empty()) {
                    out<<"\ndefine i32 @main(i32 %argc, ptr %argv) {\nentry:\n  call void @omni_runtime_begin()\n  call void @omni_runtime_configure(i32 %argc, ptr %argv)\n  %r = call i32 @omni.fn."<<p.module<<".main()\n  call void @omni_runtime_end()\n  %status = and i32 %r, 255\n  ret i32 %status\n}\n\n";
                } else {
                    const Function* selected=nullptr;
                    for(const auto& function:p.functions)
                        if(function.key==hostFunctionKey){selected=&function;break;}
                    if(!selected)fail("E_HOST_ENTRY","selected function missing in LLVM lowering");
                    out<<"\ndefine hidden void @omni_host_call(ptr %args, ptr %result) {\nentry:\n";
                    for(size_t i=0;i<selected->params.size();i++) {
                        out<<"  %ap"<<i<<" = getelementptr ptr, ptr %args, i32 "<<i<<"\n";
                        out<<"  %pp"<<i<<" = load ptr, ptr %ap"<<i<<"\n";
                        out<<"  %av"<<i<<" = load "<<lt(selected->params[i].type)<<", ptr %pp"<<i<<"\n";
                    }
                    out<<"  %value = call "<<lt(selected->result)<<" @omni.fn."<<hostFunctionKey<<"(";
                    for(size_t i=0;i<selected->params.size();i++) {
                        if(i)out<<", ";
                        out<<lt(selected->params[i].type)<<" %av"<<i;
                    }
                    out<<")\n  store "<<lt(selected->result)<<" %value, ptr %result\n  ret void\n}\n";
                }
                // An image with an exception/interrupt table (--exception-handler) takes its exceptions on the very stack its code runs on: the SysV red zone (128 bytes below %rsp that a leaf function
                // may use without moving %rsp) would be overwritten by the CPU's own push. So every function of such an image carries `noredzone` in the artifact, whatever flags the consumer's backend
                // is given. An image without that table keeps exactly the IR it always had (no drift for programs that do not use the feature).
                const bool noRedZone=prof&&prof->triple.rfind("x86_64",0)==0&&!prof->exceptionHandler.empty();
                const bool sectioned=prof&&prof->pvhNote&&!prof->entrySection.empty();
                if(noRedZone||sectioned) {
                    std::istringstream in(out.str()); std::string line,all; const std::string sec=" section \""+(prof?prof->entrySection:std::string())+"\"";
                    while(std::getline(in,line)) {
                        if(line.rfind("define ",0)==0) {
                            const auto brace=line.rfind(" {");
                            if(brace!=std::string::npos) {
                                if(sectioned&&line.rfind("define internal ",0)==0&&line.find(" section ")==std::string::npos)line.insert(brace,sec);
                                if(noRedZone&&line.find(" noredzone")==std::string::npos) { const auto at=line.find(" section \""); line.insert(at!=std::string::npos?at:line.rfind(" {")," noredzone"); }
                            }
                        }
                        all+=line+"\n";
                    }
                    return all+globals.str()+lateText();
                }
                return out.str()+globals.str()+lateText();
            }
        };
    }
    std::string emitLLVM(const Program& p)  {
        requireMain(p);
        return LLVM(p).run();
    }
    std::string emitLLVMTarget(const Program& p,const TargetProfile& profile) {
        requireMain(p);
        LLVM g(p);
        g.setProfile(&profile);
        return g.run();
    }
    std::string emitLLVMHost(const Program& p,const std::string& functionKey) {
        return LLVM(p).run(functionKey);
    }
}

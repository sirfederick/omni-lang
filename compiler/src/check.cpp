#include "omni.hpp"
#include <cstring>
namespace omni  {
    namespace  {
        uint64_t intMask(const Type&t){ auto w=integerWidth(t); return w==64?UINT64_MAX:((uint64_t(1)<<w)-1); }
        int64_t signedBits(const Type&t,uint64_t bits){
            const auto w=integerWidth(t); bits&=intMask(t);
            if(w==64)return static_cast<int64_t>(bits);
            const uint64_t sign=uint64_t(1)<<(w-1);
            return (bits&sign)?static_cast<int64_t>(bits|(UINT64_MAX<<w)):static_cast<int64_t>(bits);
        }
        uint64_t encodeSigned(const Type&t,int64_t v){ return static_cast<uint64_t>(v)&intMask(t); }
        bool positiveLiteralFits(const Type&t,uint64_t v){ return isSignedInteger(t)?v<=static_cast<uint64_t>(integerMaxSigned(t)):v<=integerMaxUnsigned(t); }
        bool negativeMagnitudeFits(const Type&t,uint64_t v){
            if(!isSignedInteger(t))return false;
            const auto w=integerWidth(t); const uint64_t maxMag=w==64?(uint64_t(1)<<63):(uint64_t(1)<<(w-1)); return v<=maxMag;
        }
        uint64_t checkedCastBits(const Type&src,const Type&dst,uint64_t bits){
            if(isSignedInteger(src)) {
                const int64_t v=signedBits(src,bits);
                if(isSignedInteger(dst)) {
                    if(v<integerMinSigned(dst)||v>integerMaxSigned(dst))fail("E_CAST_RANGE","conversion fuera de rango: "+typeName(src)+" -> "+typeName(dst));
                    return encodeSigned(dst,v);
                }
                if(v<0||static_cast<uint64_t>(v)>integerMaxUnsigned(dst))fail("E_CAST_RANGE","conversion fuera de rango: "+typeName(src)+" -> "+typeName(dst));
                return static_cast<uint64_t>(v)&intMask(dst);
            }
            const uint64_t v=bits&intMask(src);
            if(isSignedInteger(dst)) {
                if(v>static_cast<uint64_t>(integerMaxSigned(dst)))fail("E_CAST_RANGE","conversion fuera de rango: "+typeName(src)+" -> "+typeName(dst));
                return encodeSigned(dst,static_cast<int64_t>(v));
            }
            if(v>integerMaxUnsigned(dst))fail("E_CAST_RANGE","conversion fuera de rango: "+typeName(src)+" -> "+typeName(dst));
            return v&intMask(dst);
        }
        double floatValue(const Type&t,uint64_t bits){
            if(t.kind==Type::F32)return static_cast<double>(std::bit_cast<float>(static_cast<uint32_t>(bits)));
            if(t.kind==Type::F64)return std::bit_cast<double>(bits);
            fail("E_TYPE","valor flotante requiere f32/f64");
        }
        uint64_t floatBits(const Type&t,double value){
            if(t.kind==Type::F32)return static_cast<uint64_t>(std::bit_cast<uint32_t>(static_cast<float>(value)));
            if(t.kind==Type::F64)return std::bit_cast<uint64_t>(value);
            fail("E_TYPE","bits flotantes requieren f32/f64");
        }
        uint64_t numericCastBits(const Type&src,const Type&dst,uint64_t bits){
            if(isInteger(src)&&isInteger(dst))return checkedCastBits(src,dst,bits);
            if(isFloat(src)&&isFloat(dst))return floatBits(dst,floatValue(src,bits));
            if(isInteger(src)&&isFloat(dst)){
                const double v=isSignedInteger(src)?static_cast<double>(signedBits(src,bits)):static_cast<double>(bits&intMask(src));
                return floatBits(dst,v);
            }
            if(isFloat(src)&&isInteger(dst)){
                const double v=floatValue(src,bits);
                if(!std::isfinite(v))fail("E_CAST_RANGE","conversion float->integer requiere valor finito");
                if(isSignedInteger(dst)){
                    if(v<static_cast<double>(integerMinSigned(dst))||v>static_cast<double>(integerMaxSigned(dst)))
                        fail("E_CAST_RANGE","conversion fuera de rango: "+typeName(src)+" -> "+typeName(dst));
                    return encodeSigned(dst,static_cast<int64_t>(v));
                }
                if(v<0.0||v>static_cast<double>(integerMaxUnsigned(dst)))
                    fail("E_CAST_RANGE","conversion fuera de rango: "+typeName(src)+" -> "+typeName(dst));
                return static_cast<uint64_t>(v)&intMask(dst);
            }
            fail("E_TYPE","conversion numerica no soportada: "+typeName(src)+" -> "+typeName(dst));
        }
        uint64_t floatBinaryBits(const Type&t,const std::string&op,uint64_t a,uint64_t b){
            if(t.kind==Type::F32){
                const float x=std::bit_cast<float>(static_cast<uint32_t>(a));
                const float y=std::bit_cast<float>(static_cast<uint32_t>(b));
                float r=0.0f;
                if(op=="+")r=x+y; else if(op=="-")r=x-y; else if(op=="*")r=x*y; else if(op=="/")r=x/y;
                else fail("E_TYPE","operacion f32 no soportada: "+op);
                return static_cast<uint64_t>(std::bit_cast<uint32_t>(r));
            }
            if(t.kind==Type::F64){
                const double x=std::bit_cast<double>(a),y=std::bit_cast<double>(b);
                double r=0.0;
                if(op=="+")r=x+y; else if(op=="-")r=x-y; else if(op=="*")r=x*y; else if(op=="/")r=x/y;
                else fail("E_TYPE","operacion f64 no soportada: "+op);
                return std::bit_cast<uint64_t>(r);
            }
            fail("E_TYPE","operacion flotante requiere f32/f64");
        }
        bool validUnicodeScalar(uint32_t cp){
            return cp<=0x10ffffu && !(cp>=0xd800u&&cp<=0xdfffu);
        }
        bool decodeUtf8Scalar(const std::string& s,size_t& pos,uint32_t& cp){
            if(pos>=s.size())return false;
            const auto c0=static_cast<unsigned char>(s[pos++]);
            if(c0<0x80){ cp=c0; return true; }
            int need=0; uint32_t min=0;
            if((c0&0xe0u)==0xc0u){need=1;cp=c0&0x1fu;min=0x80u;}
            else if((c0&0xf0u)==0xe0u){need=2;cp=c0&0x0fu;min=0x800u;}
            else if((c0&0xf8u)==0xf0u){need=3;cp=c0&0x07u;min=0x10000u;}
            else return false;
            while(need--){
                if(pos>=s.size())return false;
                const auto cx=static_cast<unsigned char>(s[pos++]);
                if((cx&0xc0u)!=0x80u)return false;
                cp=(cp<<6)|(cx&0x3fu);
            }
            return cp>=min&&validUnicodeScalar(cp);
        }
        uint32_t utf8ScalarCount(const std::string& s){
            size_t p=0; uint32_t n=0,cp=0;
            while(p<s.size()){
                if(!decodeUtf8Scalar(s,p,cp))fail("E_UTF8","Text interno UTF-8 invalido");
                if(n==UINT32_MAX)fail("E_LIMIT","Text excede conteo scalar u32");
                ++n;
            }
            return n;
        }
        bool utf8ScalarAt(const std::string& s,uint32_t index,uint32_t& out){
            size_t p=0; uint32_t n=0,cp=0;
            while(p<s.size()){
                if(!decodeUtf8Scalar(s,p,cp))fail("E_UTF8","Text interno UTF-8 invalido");
                if(n++==index){out=cp;return true;}
            }
            return false;
        }
        std::string encodeUnicodeScalar(uint32_t cp){
            if(!validUnicodeScalar(cp))fail("E_CHAR_RANGE","valor no es Unicode scalar");
            std::string out;
            if(cp<=0x7fu)out.push_back(static_cast<char>(cp));
            else if(cp<=0x7ffu){
                out.push_back(static_cast<char>(0xc0u|(cp>>6)));
                out.push_back(static_cast<char>(0x80u|(cp&0x3fu)));
            } else if(cp<=0xffffu){
                out.push_back(static_cast<char>(0xe0u|(cp>>12)));
                out.push_back(static_cast<char>(0x80u|((cp>>6)&0x3fu)));
                out.push_back(static_cast<char>(0x80u|(cp&0x3fu)));
            } else {
                out.push_back(static_cast<char>(0xf0u|(cp>>18)));
                out.push_back(static_cast<char>(0x80u|((cp>>12)&0x3fu)));
                out.push_back(static_cast<char>(0x80u|((cp>>6)&0x3fu)));
                out.push_back(static_cast<char>(0x80u|(cp&0x3fu)));
            }
            return out;
        }
        uint64_t checkedIntOp(const Type&t,const std::string&op,uint64_t a,uint64_t b){
            if(isSignedInteger(t)) {
                const int64_t x=signedBits(t,a),y=signedBits(t,b);
                if(op=="/"||op=="%") {
                    if(y==0)fail("E_DIVZERO","division por cero");
                    if(x==integerMinSigned(t)&&y==-1)fail("E_OVERFLOW","division signed fuera de "+typeName(t));
                    return encodeSigned(t,op=="/"?x/y:x%y);
                }
                int64_t r=0; bool ov=false;
                if(op=="+")ov=__builtin_add_overflow(x,y,&r);
                else if(op=="-")ov=__builtin_sub_overflow(x,y,&r);
                else if(op=="*")ov=__builtin_mul_overflow(x,y,&r);
                else fail("E_INTERNAL","operacion checked desconocida");
                if(ov||r<integerMinSigned(t)||r>integerMaxSigned(t))fail("E_OVERFLOW","aritmetica fuera de "+typeName(t));
                return encodeSigned(t,r);
            }
            const uint64_t x=a&intMask(t),y=b&intMask(t);
            if(op=="/"||op=="%") { if(y==0)fail("E_DIVZERO","division por cero"); return (op=="/"?x/y:x%y)&intMask(t); }
            uint64_t r=0; bool ov=false;
            if(op=="+")ov=__builtin_add_overflow(x,y,&r);
            else if(op=="-")ov=__builtin_sub_overflow(x,y,&r);
            else if(op=="*")ov=__builtin_mul_overflow(x,y,&r);
            else fail("E_INTERNAL","operacion checked desconocida");
            if(ov||r>integerMaxUnsigned(t))fail("E_OVERFLOW","aritmetica fuera de "+typeName(t));
            return r&intMask(t);
        }
        uint64_t wrappingIntOp(const Type&t,const std::string&op,uint64_t a,uint64_t b){
            const uint64_t x=a&intMask(t),y=b&intMask(t); uint64_t r=0;
            if(op=="+%")r=x+y; else if(op=="-%")r=x-y; else if(op=="*%")r=x*y; else fail("E_INTERNAL","operacion wrapping desconocida");
            return r&intMask(t);
        }
        uint64_t saturatingIntOp(const Type&t,const std::string&op,uint64_t a,uint64_t b){
            if(isSignedInteger(t)) {
                const int64_t x=signedBits(t,a),y=signedBits(t,b); int64_t r=0; bool ov=false;
                if(op=="+|")ov=__builtin_add_overflow(x,y,&r);
                else if(op=="-|")ov=__builtin_sub_overflow(x,y,&r);
                else if(op=="*|")ov=__builtin_mul_overflow(x,y,&r);
                else fail("E_INTERNAL","operacion saturating desconocida");
                if(ov) {
                    if(op=="+|")r=x>=0?integerMaxSigned(t):integerMinSigned(t);
                    else if(op=="-|")r=(x>=0&&y<0)?integerMaxSigned(t):integerMinSigned(t);
                    else r=((x<0)==(y<0))?integerMaxSigned(t):integerMinSigned(t);
                }
                if(r<integerMinSigned(t))r=integerMinSigned(t);
                if(r>integerMaxSigned(t))r=integerMaxSigned(t);
                return encodeSigned(t,r);
            }
            const uint64_t x=a&intMask(t),y=b&intMask(t),max=integerMaxUnsigned(t); uint64_t r=0; bool ov=false;
            if(op=="+|")ov=__builtin_add_overflow(x,y,&r);
            else if(op=="-|") { if(x<y)return 0; r=x-y; }
            else if(op=="*|")ov=__builtin_mul_overflow(x,y,&r);
            else fail("E_INTERNAL","operacion saturating desconocida");
            if(ov||r>max)r=max;
            return r&intMask(t);
        }
        struct Binding  {
            Type type;
            bool mut;
            int id;
        };
        bool concreteGenericArg(const Type& t) {
            if(t.kind==Type::Param||t.kind==Type::Unknown)return false;
            for(const auto& p:t.parts)if(!concreteGenericArg(p))return false;
            return true;
        }
        bool genericConstraintAccepts(const std::string& c,const Type& t) {
            if(c=="Any")return true;
            if(c=="Integer")return isInteger(t);
            if(c=="SignedInteger")return isSignedInteger(t);
            if(c=="UnsignedInteger")return isInteger(t)&&!isSignedInteger(t);
            if(c=="Scalar")return isInteger(t)||isFloat(t)||t.kind==Type::Bool||t.kind==Type::Char;
            if(c=="Plain") {
                const auto k=t.kind;
                if(k==Type::Resource||k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::Result||k==Type::View||k==Type::Param||k==Type::Unknown)return false;
                for(const auto& p:t.parts)if(!genericConstraintAccepts("Plain",p))return false;
                return true;
            }
            fail("E_GENERIC_CONSTRAINT","unknown generic constraint: "+c);
        }
        bool builtinGenericConstraint(const std::string& c) {
            static const std::set<std::string> builtins={"Any","Integer","SignedInteger","UnsignedInteger","Scalar","Plain"};
            return builtins.count(c)!=0;
        }
        Type substituteGenericType(Type t,const std::map<std::string,Type>& map,Loc l) {
            if(t.kind==Type::Param) {
                auto it=map.find(t.name); if(it==map.end())fail("E_GENERIC_INTERNAL","unbound generic type parameter: "+t.name,l); return it->second;
            }
            // CP-01/CP-05: `Resource<T>`, `Borrow<T>` and `BorrowMut<T>` name their record in `name`, not in `parts`; when that name is a generic
            // parameter (or `Self` in a trait) it is replaced by the record the argument stands for. Only a nominal record can be lent or owned.
            if((t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::BorrowMut)&&t.parts.empty()) {
                auto it=map.find(t.name);
                if(it!=map.end()) {
                    if(it->second.kind!=Type::Record)fail("E_GENERIC_CONSTRAINT","un Resource/Borrow requiere un registro nominal como argumento: "+typeName(it->second),l);
                    t.name=it->second.name; return t;   // a generic argument is resolved to its concrete instance (own name, no parts) before it reaches this point
                }
            }
            for(auto& p:t.parts)p=substituteGenericType(p,map,l);
            return t;
        }
        void substituteGenericExpr(Expr& e,const std::map<std::string,Type>& map) {
            e.annotation=substituteGenericType(e.annotation,map,e.loc);
            for(auto& t:e.typeArgs)t=substituteGenericType(t,map,e.loc);
            for(auto& a:e.args)substituteGenericExpr(a,map);
        }
        void substituteGenericBlock(std::vector<Stmt>& b,const std::map<std::string,Type>& map) {
            for(auto& s:b) {
                s.declared=substituteGenericType(s.declared,map,s.loc);
                substituteGenericExpr(s.expr,map);
                substituteGenericBlock(s.body,map); substituteGenericBlock(s.other,map);
                for(auto& a:s.arms)substituteGenericBlock(a,map);
            }
        }
        // ---- CP-05c (TRY_PROPAGATION_CANDIDATE.md): `expr?` is lowered, before any checking, into ordinary statements:
        //   let __try_tN = expr
        //   match __try_tN { Ok(__try_vN) { <rest of the block, with `expr?` replaced by __try_vN> }
        //                    Err(__try_eN) { return Err<U,E>(__try_eN) } }          (Some/None for Option)
        // so the rest of the block lives in the success arm and every ownership/borrow/cleanup rule applies unchanged.
        bool exprImpureForTry(const Expr& e) {
            switch(e.kind) {
                case Expr::Call:case Expr::ClosureCall:case Expr::Join:case Expr::Cancel:case Expr::Deadline:
                case Expr::Channel:case Expr::Send:case Expr::Receive:case Expr::Close:return true;
                default:return false;
            }
        }
        Expr* findTryInEvaluationOrder(Expr& e,bool& impure,bool& violation) {
            if(e.kind==Expr::Try) {
                const bool before=impure;
                if(auto* inner=findTryInEvaluationOrder(e.args.at(0),impure,violation))return inner;
                if(before)violation=true;
                return &e;
            }
            for(auto& a:e.args)if(auto* found=findTryInEvaluationOrder(a,impure,violation))return found;
            if(exprImpureForTry(e))impure=true;
            return nullptr;
        }
        bool containsTry(const Expr& e) {
            if(e.kind==Expr::Try)return true;
            for(const auto& a:e.args)if(containsTry(a))return true;
            return false;
        }
        // CP-07 (spec/STATIC_DATA_CANDIDATE.md): a use of a `const` is a call of its function. It is resolved BEFORE the body is checked, because the indexing and iteration rules look at the
        // base of `TABLE[i]` and at the iterable of `for x in TABLE` as places. A name the function itself binds (a parameter, a let, a loop variable, a pattern) is never rewritten.
        void constBinders(const std::vector<Stmt>& block,std::set<std::string>& out) {
            for(const auto& s:block) {
                if(!s.name.empty())out.insert(s.name);
                if(!s.otherName.empty())out.insert(s.otherName);
                for(const auto& n:s.names)out.insert(n);
                for(const auto& n:s.armNames)out.insert(n);
                constBinders(s.body,out); constBinders(s.other,out);
                for(const auto& arm:s.arms)constBinders(arm,out);
            }
        }
        void foldTarget(Expr& e) {
            const auto& facts=targetFacts();
            const std::string n=e.text.substr(7);
            auto number=[&](uint64_t v){ e.kind=Expr::Number; e.value=v; e.annotation=Type(Type::U32); e.args.clear(); e.text.clear(); };
            auto boolean=[&](bool v){ e.kind=Expr::Boolean; e.value=v?1:0; e.args.clear(); e.text.clear(); };
            auto literal=[&]()->std::string{
                if(e.args.size()!=1||e.args[0].kind!=Expr::Text)fail("E_TARGET","target."+n+" requiere un nombre literal entre comillas",e.loc);
                return e.args[0].text;
            };
            auto noArguments=[&]{ if(!e.args.empty())fail("E_TARGET","target."+n+" no recibe argumentos",e.loc); };
            if(n=="pointer_width") { noArguments(); number(facts.pointerWidth); }
            else if(n=="little_endian") { noArguments(); boolean(facts.littleEndian); }
            else if(n=="hosted") { noArguments(); boolean(facts.hosted); }
            else if(n=="arch_is") {
                const auto name=literal();
                if(name!="x86_64"&&name!="i386")fail("E_TARGET","arquitectura desconocida: "+name+" (x86_64, i386)",e.loc);
                boolean(name==facts.arch);
            }
            else if(n=="has") {
                static const std::set<std::string> known={"x87","sse2","sse3","ssse3","sse41","sse42","avx","avx2","fma","aes","pclmul","popcnt","bmi1","bmi2","rdrand","rdseed"};
                const auto name=literal();
                if(!known.count(name))fail("E_TARGET","caracteristica de CPU desconocida: "+name,e.loc);
                boolean(facts.features.count(name)!=0);
            }
            else fail("E_TARGET","target."+n+" no existe (pointer_width, little_endian, hosted, arch_is, has)",e.loc);
        }
        void constRewrite(const Program& p,const std::string& module,const std::set<std::string>& bound,Expr& e) {
            for(auto& a:e.args)constRewrite(p,module,bound,a);
            if(e.kind==Expr::Call&&e.text.rfind("target.",0)==0)foldTarget(e);
            if(e.kind==Expr::Ref&&!bound.count(e.text)) {
                for(const auto& f:p.functions)if(f.isConst&&f.module==module&&f.name==e.text) { e.kind=Expr::Call; e.args.clear(); return; }
            }
            if(e.kind==Expr::Field&&e.args.size()==1&&e.args[0].kind==Expr::Ref&&!bound.count(e.args[0].text)) {   // `alias.NAME`: a constant of an imported module
                for(const auto& m:p.modules)if(m.name==module)for(const auto& im:m.imports)if(im.alias==e.args[0].text)
                    for(const auto& f:p.functions)if(f.isConst&&f.module==im.target&&f.name==e.text) {
                        if(!f.pub&&im.target!=module)fail("E_VISIBILITY","constante privada: "+im.alias+"."+e.text,e.loc);
                        e.text=im.alias+"."+e.text; e.kind=Expr::Call; e.args.clear(); return;
                    }
            }
        }
        void constStatements(const Program& p,const std::string& module,const std::set<std::string>& bound,std::vector<Stmt>& block) {
            for(auto& s:block) {
                constRewrite(p,module,bound,s.expr);
                constStatements(p,module,bound,s.body); constStatements(p,module,bound,s.other);
                for(auto& arm:s.arms)constStatements(p,module,bound,arm);
            }
        }
        void resolveConstants(const Program& p,Function& f) {
            std::set<std::string> bound;
            for(const auto& a:f.params)bound.insert(a.name);
            constBinders(f.body,bound);
            constStatements(p,f.module,bound,f.body);
        }
        void lowerTryBlock(std::vector<Stmt>& block,const Function& fn,int& counter) {
            for(size_t i=0;i<block.size();++i) {
                Stmt& s=block[i];
                if(s.kind==Stmt::Loop&&containsTry(s.expr))fail("E_TRY_POSITION","? no se admite en la condicion de un bucle (se evaluaria varias veces)",s.loc);
                const bool liftable=s.kind==Stmt::Let||s.kind==Stmt::Var||s.kind==Stmt::Assign||s.kind==Stmt::Return||s.kind==Stmt::Print||
                                    s.kind==Stmt::If||s.kind==Stmt::ForEach||s.kind==Stmt::Match||s.kind==Stmt::MatchOption||
                                    s.kind==Stmt::MatchEnum||s.kind==Stmt::Destructure;
                bool impure=false,violation=false;
                Expr* found=liftable?findTryInEvaluationOrder(s.expr,impure,violation):nullptr;
                if(found) {
                    const Loc l=found->loc;
                    if(violation)fail("E_TRY_ORDER","? debe evaluarse antes que cualquier otra llamada de la expresion; ligue antes los operandos con let",l);
                    if(fn.result.kind!=Type::Result&&fn.result.kind!=Type::Option)
                        fail("E_TRY_CONTEXT","? requiere que la funcion devuelva Result u Option",l);
                    const int n=counter++;
                    const std::string tmp="__try_t"+std::to_string(n),val="__try_v"+std::to_string(n),err="__try_e"+std::to_string(n);
                    // `let x = expr?` binds the payload directly under the user's name in the success arm: no copy, so a
                    // Resource payload is moved into x exactly as in `match … { Ok(x) { … } }`.
                    const bool directLet=s.kind==Stmt::Let&&found==&s.expr&&s.declared.kind==Type::Unknown;
                    const std::string payloadName=directLet?s.name:val;
                    Stmt bind; bind.kind=Stmt::Let; bind.loc=l; bind.name=tmp; bind.expr=std::move(found->args.at(0));
                    std::vector<Stmt> rest;
                    if(!directLet) {
                        Expr ref; ref.kind=Expr::Ref; ref.loc=l; ref.text=val; *found=ref;
                        rest.push_back(std::move(s));
                    }
                    for(size_t j=i+1;j<block.size();++j)rest.push_back(std::move(block[j]));
                    lowerTryBlock(rest,fn,counter);
                    Stmt m; m.loc=l; m.expr.kind=Expr::Ref; m.expr.loc=l; m.expr.text=tmp;
                    Stmt ret; ret.kind=Stmt::Return; ret.loc=l;
                    if(fn.result.kind==Type::Result) {
                        Expr propagated; propagated.kind=Expr::Err; propagated.loc=l; propagated.annotation=fn.result;
                        Expr arg; arg.kind=Expr::Ref; arg.loc=l; arg.text=err; propagated.args.push_back(arg);
                        ret.expr=propagated;
                        m.kind=Stmt::Match; m.name=payloadName; m.body=std::move(rest); m.otherName=err; m.other.push_back(std::move(ret));
                    } else {
                        Expr absent; absent.kind=Expr::None; absent.loc=l; absent.annotation=fn.result;
                        ret.expr=absent;
                        m.kind=Stmt::MatchOption; m.name=payloadName; m.body=std::move(rest); m.other.push_back(std::move(ret));
                    }
                    block.resize(i);
                    block.push_back(std::move(bind)); block.push_back(std::move(m));
                    return;
                }
                lowerTryBlock(s.body,fn,counter); lowerTryBlock(s.other,fn,counter);
                for(auto& arm:s.arms)lowerTryBlock(arm,fn,counter);
            }
        }
        void lowerTry(Program& p) {
            for(auto* group:{&p.functions,&p.genericTemplates}) for(auto& f:*group){ resolveConstants(p,f); int counter=0; lowerTryBlock(f.body,f,counter); }
            for(auto& d:p.traitImpls)for(auto& f:d.methods){ resolveConstants(p,f); int counter=0; lowerTryBlock(f.body,f,counter); }
        }
        std::string genericKeyFor(const std::string& module,const std::string& name){return module+"."+name;}
        Function* resolveGenericTemplate(const std::map<std::string,ModuleInfo*>& modules,const std::map<std::string,Function*>& templates,const std::string& callerModule,const std::string& name,Loc l) {
            std::string targetModule=callerModule, fnName=name;
            auto dot=name.find('.');
            if(dot!=std::string::npos){
                if(name.find('.',dot+1)!=std::string::npos)return nullptr;
                auto prefix=name.substr(0,dot); fnName=name.substr(dot+1);
                if(prefix==callerModule)targetModule=callerModule;
                else {
                    auto mi=modules.at(callerModule); bool found=false;
                    for(auto& im:mi->imports)if(im.alias==prefix){targetModule=im.target;found=true;break;}
                    if(!found)return nullptr;
                }
            }
            auto it=templates.find(genericKeyFor(targetModule,fnName));
            if(it==templates.end())return nullptr;
            if(targetModule!=callerModule&&!it->second->pub)fail("E_VISIBILITY","generic function is private: "+name,l);
            return it->second;
        }
        void expandGenerics(Program& p) {
            std::map<std::string,ModuleInfo*> modules; for(auto& m:p.modules)modules[m.name]=&m;
            std::map<std::string,Function*> templates;
            std::map<std::string,const TraitDef*> traits;
            // The trait key of a bound: `Codec` is a trait of the declaring module, `alias.Allocator` a pub trait of the module the declaring module imported as `alias`.
            // An alias that is not an import stays unresolved (the key then names no trait and the bound is refused).
            auto constraintTraitKey=[&](const std::string& module,const std::string& constraint,Loc l=Loc{})->std::string{
                const auto dot=constraint.find('.');
                if(dot==std::string::npos)return module+"."+constraint;
                const std::string prefix=constraint.substr(0,dot),name=constraint.substr(dot+1);
                auto mi=modules.find(module);
                if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==prefix) {
                    const std::string key=im.target+"."+name;
                    if(im.target!=module&&traits.count(key)&&!traits.at(key)->pub)fail("E_VISIBILITY","trait privado: "+constraint,l);
                    return key;
                }
                return module+"."+constraint;
            };
            for(auto& d:p.traits){
                if(!modules.count(d.module)||!validIdentifier(d.name))fail("E_TRAIT","trait invalido",d.loc);
                d.key=d.module+"."+d.name;
                if(!traits.emplace(d.key,&d).second)fail("E_DUPLICATE","trait duplicado: "+d.key,d.loc);
            }
            for(auto& f:p.genericTemplates){
                if(!modules.count(f.module)||!validIdentifier(f.name))fail("E_GENERIC_DECL","invalid generic function declaration",f.loc);
                auto k=genericKeyFor(f.module,f.name); if(templates.count(k))fail("E_DUPLICATE","duplicate generic function: "+k,f.loc);
                std::set<std::string> names;
                for(auto& g:f.generics){
                    if(!validIdentifier(g.name)||!names.insert(g.name).second)fail("E_GENERIC_DECL","invalid/duplicate generic parameter: "+g.name,g.loc);
                    if(!builtinGenericConstraint(g.constraint)&&!traits.count(constraintTraitKey(f.module,g.constraint,g.loc)))fail("E_GENERIC_CONSTRAINT","unsupported generic constraint: "+g.constraint,g.loc);
                }
                templates[k]=&f;
            }
            // The types a template names in its signature exist when it is declared, as they do for any other function: a typo in a template nobody instantiates was accepted here and refused
            // later by every consumer that needs the identity of the type (the projection into OSNMF, ONME).
            for(const auto& f:p.genericTemplates) {
                std::set<std::string> bound; for(const auto& g:f.generics)bound.insert(g.name);
                std::function<void(const Type&)> demand=[&](const Type& u){
                    if((u.kind==Type::Record||u.kind==Type::Enum)&&u.key.empty())fail("E_TYPE","tipo inexistente: "+u.name,f.loc);
                    // Resource<R>, Borrow<R> and BorrowMut<R> name their nominal in `name`: Buffer, a generic parameter, or a type that resolved to its module (a qualified name)
                    const bool nominal=u.kind==Type::Resource||u.kind==Type::Borrow||u.kind==Type::BorrowMut;
                    if(nominal&&u.name!="Buffer"&&!bound.count(u.name)&&u.name.find('.')==std::string::npos)fail("E_RESOURCE_TYPE","Resource<"+u.name+">: solo Buffer o un struct declarado de un campo u64",f.loc);
                    for(const auto& x:u.parts)demand(x);
                };
                demand(resolveOpenType(p,f.module,bound,f.result));
                for(const auto& a:f.params)demand(resolveOpenType(p,f.module,bound,a.type));
            }
            for(auto& f:p.functions)if(templates.count(genericKeyFor(f.module,f.name)))fail("E_DUPLICATE","generic/non-generic function name collision: "+f.name,f.loc);
            for(const auto& r:p.records)if(templates.count(genericKeyFor(r.module,r.name)))fail("E_DUPLICATE","generic function/type name collision: "+r.name,r.loc);
            for(const auto& e:p.enums)if(templates.count(genericKeyFor(e.module,e.name)))fail("E_DUPLICATE","generic function/type name collision: "+e.name,e.loc);
            std::map<std::string,std::string> specializationName;
            std::map<std::string,Function> generatedByKey;
            std::vector<std::string> generationOrder;
            size_t generatedCount=0;
            std::function<void(Expr&,const std::string&)> scanExpr;
            std::function<void(std::vector<Stmt>&,const std::string&)> scanBlock;
            std::map<std::string,const RecordDef*> genericRecords;
            std::map<std::string,const EnumDef*> genericEnums;
            for(const auto& r:p.records)genericRecords.emplace(r.module+"."+r.name,&r);
            for(const auto& e:p.enums)genericEnums.emplace(e.module+"."+e.name,&e);

            std::function<Type(Type,const std::string&,Loc)> resolveGenericArgument;
            resolveGenericArgument=[&](Type t,const std::string& callerModule,Loc l)->Type {
                if(t.kind==Type::Record||t.kind==Type::Enum){
                    const bool validatedSubstitution=!t.key.empty();
                    std::string resolvedKey;
                    if(!t.key.empty())resolvedKey=t.key;
                    else {
                        const auto dot=t.name.find('.');
                        if(dot==std::string::npos)resolvedKey=callerModule+"."+t.name;
                        else {
                            const auto prefix=t.name.substr(0,dot),rest=t.name.substr(dot+1);
                            if(prefix==callerModule)resolvedKey=prefix+"."+rest;
                            else {
                                auto mi=modules.find(callerModule);bool found=false;
                                if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==prefix){resolvedKey=im.target+"."+rest;found=true;break;}
                                if(!found)fail("E_IMPORT","alias no importado en argumento generico: "+prefix,l);
                            }
                        }
                    }
                    auto ri=genericRecords.find(resolvedKey);auto ei=genericEnums.find(resolvedKey);
                    if(ri==genericRecords.end()&&ei==genericEnums.end())fail("E_TYPE","tipo generico nominal inexistente: "+t.name,l);
                    const auto targetModule=resolvedKey.substr(0,resolvedKey.find('.'));
                    if(ri!=genericRecords.end()){
                        t.kind=Type::Record;
                        if(targetModule!=callerModule&&!ri->second->pub&&!validatedSubstitution)fail("E_VISIBILITY","struct privado en argumento generico: "+t.name,l);
                    } else {
                        t.kind=Type::Enum;
                        if(targetModule!=callerModule&&!ei->second->pub&&!validatedSubstitution)fail("E_VISIBILITY","enum privado en argumento generico: "+t.name,l);
                    }
                    t.key=resolvedKey;
                    return t;
                }
                for(auto& part:t.parts)part=resolveGenericArgument(part,callerModule,l);
                return t;
            };

            // `impl [alias.]Trait for Type`: the trait may live in an imported module. Orphan rule: either the trait or the implementing type belongs to the impl'"'"'s module.
            auto implTraitKey=[&](const TraitImpl& d)->std::string {
                const auto dot=d.trait.find('.');
                if(dot==std::string::npos)return d.module+"."+d.trait;
                const auto alias=d.trait.substr(0,dot),shortName=d.trait.substr(dot+1);
                std::string target;
                if(alias==d.module)target=d.module;
                else { auto mi=modules.find(d.module); if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==alias)target=im.target; }
                if(target.empty())fail("E_TRAIT","alias de trait no importado: "+alias,d.loc);
                return target+"."+shortName;
            };
            std::set<std::string> traitImplementations;
            for(auto& d:p.traitImpls){
                const auto traitKey=implTraitKey(d);
                if(!traits.count(traitKey))fail("E_TRAIT","trait inexistente para impl: "+d.trait,d.loc);
                const auto traitModule=traitKey.substr(0,traitKey.find('.'));
                if(traitModule!=d.module&&!traits.at(traitKey)->pub)fail("E_VISIBILITY","trait privado: "+d.trait,d.loc);
                auto resolved=resolveGenericArgument(d.forType,d.module,d.loc);
                if(!concreteGenericArg(resolved))fail("E_TRAIT","impl requiere tipo concreto",d.loc);
                if(traitModule!=d.module){
                    const bool localType=(resolved.kind==Type::Record||resolved.kind==Type::Enum)&&resolved.key.substr(0,resolved.key.find('.'))==d.module;
                    if(!localType)fail("E_TRAIT_COHERENCE","impl de un trait ajeno para un tipo ajeno: "+d.trait+" for "+typeName(resolved),d.loc);
                }
                d.forType=resolved;
                if(!traitImplementations.insert(traitKey+"|"+canonicalTypeIdentity(resolved)).second)
                    fail("E_TRAIT_COHERENCE","impl duplicado: "+traitKey,d.loc);
            }
            // ---- CP-05b (TRAIT_METHODS_CANDIDATE.md): static-dispatch trait methods. Each impl method is checked against the
            // trait signature (Self := implementing type; capabilities may not exceed the trait's) and specialized into an
            // ordinary function named <method>__impl_<hash>; calls are the explicit `Trait.method<Type>(args)`.
            std::map<std::string,std::string> traitMethodImpl;
            std::vector<Function> implFunctions;
            for(auto& d:p.traitImpls){
                const auto traitKey=implTraitKey(d);
                const TraitDef* td=traits.at(traitKey);
                const auto typeId=canonicalTypeIdentity(d.forType);
                const std::map<std::string,Type> selfSub{{"Self",d.forType}};
                const auto declaringModule=traitKey.substr(0,traitKey.find('.'));   // the types a trait signature names are resolved where the trait is declared
                std::set<std::string> defined;
                for(auto& m:d.methods){
                    if(!defined.insert(m.name).second)fail("E_TRAIT_METHOD","metodo duplicado en impl: "+m.name,m.loc);
                    const Function* sig=nullptr;
                    for(const auto& tm:td->methods)if(tm.name==m.name)sig=&tm;
                    if(!sig)fail("E_TRAIT_METHOD","el trait "+d.trait+" no declara el metodo "+m.name,m.loc);
                    if(!m.generics.empty()||!sig->generics.empty())fail("E_TRAIT_METHOD","metodos genericos no admitidos en traits (v1): "+m.name,m.loc);
                    if(m.params.size()!=sig->params.size())fail("E_TRAIT_METHOD","aridad distinta a la del trait en "+m.name,m.loc);
                    auto same=[&](const Type& implType,const Type& traitType,Loc l){
                        return canonicalTypeIdentity(resolveGenericArgument(implType,d.module,l))
                            ==canonicalTypeIdentity(resolveGenericArgument(substituteGenericType(traitType,selfSub,l),declaringModule,l));
                    };
                    for(size_t i=0;i<m.params.size();++i)
                        if(!same(m.params[i].type,sig->params[i].type,m.loc))fail("E_TRAIT_METHOD","tipo del parametro "+std::to_string(i)+" distinto al del trait en "+m.name,m.loc);
                    if(!same(m.result,sig->result,m.loc))fail("E_TRAIT_METHOD","tipo de retorno distinto al del trait en "+m.name,m.loc);
                    for(const auto& cap:m.capabilities)if(!sig->capabilities.count(cap))
                        fail("E_TRAIT_EFFECT","el metodo "+m.name+" excede las capabilities del trait: "+cap,m.loc);
                    Function g=m; g.generated=true; g.pub=td->pub; g.key.clear();
                    g.name=m.name+"__impl_"+sha256(traitKey+"|"+typeId).substr(0,12);
                    traitMethodImpl[traitKey+"|"+typeId+"|"+m.name]=d.module+"."+g.name;
                    implFunctions.push_back(std::move(g));
                }
                for(const auto& tm:td->methods)if(!defined.count(tm.name))fail("E_TRAIT_METHOD","el impl no define el metodo "+tm.name,d.loc);
            }
            for(auto& g:implFunctions){
                if(templates.count(genericKeyFor(g.module,g.name)))fail("E_DUPLICATE","colision con funcion generica: "+g.name,g.loc);
                p.functions.push_back(std::move(g));
            }

            auto ensureCanonicalGeneratedCallImport=[&](const std::string& callerModule,const std::string& targetModule,Loc l) {
                if(callerModule==targetModule)return;
                auto mi=modules.find(callerModule);if(mi==modules.end())fail("E_GENERIC_INTERNAL","caller module missing",l);
                for(const auto& im:mi->second->imports){
                    if(im.alias==targetModule){
                        if(im.target!=targetModule)fail("E_GENERIC_INTERNAL","canonical generated-call alias collision: "+targetModule,l);
                        return;
                    }
                }
                Import im;im.alias=targetModule;im.target=targetModule;im.loc=l;mi->second->imports.push_back(std::move(im));
            };

            std::function<Type(Type,const std::string&,Loc)> bindGenericArgumentToTemplateModule;
            bindGenericArgumentToTemplateModule=[&](Type t,const std::string& ownerModule,Loc l)->Type {
                if(t.kind==Type::Record||t.kind==Type::Enum){
                    if(t.key.empty())fail("E_GENERIC_INTERNAL","nominal generic argument lost canonical key",l);
                    const auto dot=t.key.find('.');if(dot==std::string::npos)fail("E_GENERIC_INTERNAL","invalid canonical nominal key",l);
                    const auto targetModule=t.key.substr(0,dot),shortName=t.key.substr(dot+1);
                    // canonical module.name (no derived import): the generated function resolves it through the generated-name rule in key()
                    t.name=targetModule==ownerModule?shortName:targetModule+"."+shortName;
                    return t;
                }
                for(auto& part:t.parts)part=bindGenericArgumentToTemplateModule(part,ownerModule,l);
                return t;
            };
            auto instantiate=[&](Function& templ,const std::vector<Type>& args,Loc l,const std::string& callerModule)->std::string {
                if(args.size()!=templ.generics.size())fail("E_GENERIC_ARGS","generic argument count mismatch for "+templ.name,l);
                std::map<std::string,Type> sub; std::string signature=genericKeyFor(templ.module,templ.name)+"<";
                for(size_t i=0;i<args.size();++i){
                    auto resolved=resolveGenericArgument(args[i],callerModule,l);
                    if(!concreteGenericArg(resolved))fail("E_GENERIC_ARGS","generic arguments must be concrete",l);
                    const auto& constraint=templ.generics[i].constraint;
                    const bool admitted=builtinGenericConstraint(constraint)
                        ? genericConstraintAccepts(constraint,resolved)
                        : traitImplementations.count(constraintTraitKey(templ.module,constraint,l)+"|"+canonicalTypeIdentity(resolved))!=0;
                    if(!admitted)fail("E_GENERIC_CONSTRAINT","type "+typeName(args[i])+" does not satisfy "+constraint,l);
                    sub[templ.generics[i].name]=bindGenericArgumentToTemplateModule(resolved,templ.module,l);
                    if(i)signature+=",";
                    signature+=canonicalTypeIdentity(resolved);
                }
                signature+=">";
                auto it=specializationName.find(signature); if(it!=specializationName.end())return it->second;
                { ++generatedCount; budgetCheck("la especializacion generica"); }
                Function g=templ; g.generics.clear(); g.generated=true; g.genericOrigin=genericKeyFor(templ.module,templ.name);
                std::function<void(const Type&)> permitType=[&](const Type& t){
                    if((t.kind==Type::Record||t.kind==Type::Enum)&&!t.key.empty())g.generatedTypeKeys.insert(t.key);
                    for(const auto& part:t.parts)permitType(part);
                };
                for(const auto& entry:sub)permitType(entry.second);
                g.name=templ.name+"__g_"+sha256(signature).substr(0,16); g.key.clear();
                for(auto& a:g.params)a.type=substituteGenericType(a.type,sub,a.loc);
                g.result=substituteGenericType(g.result,sub,g.loc);
                substituteGenericBlock(g.body,sub);
                auto key=genericKeyFor(g.module,g.name); specializationName[signature]=key;
                generatedByKey.emplace(key,std::move(g)); generationOrder.push_back(key);
                return key;
            };
            // ---- CP-05 (GENERIC_STRUCT_CANDIDATE.md): generic struct templates are monomorphized into ordinary
            // records named Name__g_<hash>; Wave/Wire/ONME only ever see the concrete specializations.
            std::map<std::string,RecordDef*> recordTemplates;
            for(auto& d:p.genericRecordTemplates){
                if(!modules.count(d.module)||!validIdentifier(d.name))fail("E_GENERIC_DECL","invalid generic struct declaration",d.loc);
                const auto k=genericKeyFor(d.module,d.name);
                if(recordTemplates.count(k)||templates.count(k))fail("E_DUPLICATE","duplicate generic declaration: "+k,d.loc);
                std::set<std::string> names;
                for(auto& g:d.generics){
                    if(!validIdentifier(g.name)||!names.insert(g.name).second)fail("E_GENERIC_DECL","invalid/duplicate generic parameter: "+g.name,g.loc);
                    if(!builtinGenericConstraint(g.constraint)&&!traits.count(constraintTraitKey(d.module,g.constraint,g.loc)))fail("E_GENERIC_CONSTRAINT","unsupported generic constraint: "+g.constraint,g.loc);
                }
                recordTemplates[k]=&d;
            }
            for(const auto& r:p.records)if(recordTemplates.count(genericKeyFor(r.module,r.name)))fail("E_DUPLICATE","generic/non-generic struct name collision: "+r.name,r.loc);
            for(const auto& e:p.enums)if(recordTemplates.count(genericKeyFor(e.module,e.name)))fail("E_DUPLICATE","generic struct/enum name collision: "+e.name,e.loc);
            std::map<std::string,EnumDef*> enumTemplates;
            for(auto& d:p.genericEnumTemplates){
                if(!modules.count(d.module)||!validIdentifier(d.name))fail("E_GENERIC_DECL","invalid generic enum declaration",d.loc);
                const auto k=genericKeyFor(d.module,d.name);
                if(enumTemplates.count(k)||recordTemplates.count(k)||templates.count(k))fail("E_DUPLICATE","duplicate generic declaration: "+k,d.loc);
                std::set<std::string> names;
                for(auto& g:d.generics){
                    if(!validIdentifier(g.name)||!names.insert(g.name).second)fail("E_GENERIC_DECL","invalid/duplicate generic parameter: "+g.name,g.loc);
                    if(!builtinGenericConstraint(g.constraint)&&!traits.count(constraintTraitKey(d.module,g.constraint,g.loc)))fail("E_GENERIC_CONSTRAINT","unsupported generic constraint: "+g.constraint,g.loc);
                }
                enumTemplates[k]=&d;
            }
            for(const auto& r:p.records)if(enumTemplates.count(genericKeyFor(r.module,r.name)))fail("E_DUPLICATE","generic enum/struct name collision: "+r.name,r.loc);
            for(const auto& e:p.enums)if(enumTemplates.count(genericKeyFor(e.module,e.name)))fail("E_DUPLICATE","generic/non-generic enum name collision: "+e.name,e.loc);
            std::map<std::string,std::string> recordSpecialization,enumSpecialization;
            std::deque<RecordDef> generatedRecords;
            std::deque<EnumDef> generatedEnums;
            size_t recordSpecializations=0;
            auto instantiateRecord=[&](RecordDef& templ,const std::vector<Type>& args,Loc l,const std::string& callerModule)->std::string {
                if(args.size()!=templ.generics.size())fail("E_GENERIC_ARGS","generic argument count mismatch for struct "+templ.name,l);
                std::map<std::string,Type> sub; std::string signature=genericKeyFor(templ.module,templ.name)+"<";
                for(size_t i=0;i<args.size();++i){
                    auto resolved=resolveGenericArgument(args[i],callerModule,l);
                    if(!concreteGenericArg(resolved))fail("E_GENERIC_ARGS","generic arguments must be concrete",l);
                    const auto& constraint=templ.generics[i].constraint;
                    const bool admitted=builtinGenericConstraint(constraint)
                        ? genericConstraintAccepts(constraint,resolved)
                        : traitImplementations.count(constraintTraitKey(templ.module,constraint,l)+"|"+canonicalTypeIdentity(resolved))!=0;
                    if(!admitted)fail("E_GENERIC_CONSTRAINT","type "+typeName(args[i])+" does not satisfy "+constraint,l);
                    sub[templ.generics[i].name]=bindGenericArgumentToTemplateModule(resolved,templ.module,l);
                    if(i)signature+=",";
                    signature+=canonicalTypeIdentity(resolved);
                }
                signature+=">";
                auto found=recordSpecialization.find(signature); if(found!=recordSpecialization.end())return found->second;
                { ++recordSpecializations; budgetCheck("la especializacion generica"); }
                RecordDef g=templ; g.generics.clear(); g.key.clear();
                g.name=templ.name+"__g_"+sha256(signature).substr(0,16);
                for(auto& f:g.fields)f.type=substituteGenericType(f.type,sub,f.loc);
                recordSpecialization[signature]=g.name;
                generatedRecords.push_back(std::move(g));
                genericRecords.emplace(generatedRecords.back().module+"."+generatedRecords.back().name,&generatedRecords.back());
                return generatedRecords.back().name;
            };
            auto instantiateEnum=[&](EnumDef& templ,const std::vector<Type>& args,Loc l,const std::string& callerModule)->std::string {
                if(args.size()!=templ.generics.size())fail("E_GENERIC_ARGS","generic argument count mismatch for enum "+templ.name,l);
                std::map<std::string,Type> sub; std::string signature=genericKeyFor(templ.module,templ.name)+"<";
                for(size_t i=0;i<args.size();++i){
                    auto resolved=resolveGenericArgument(args[i],callerModule,l);
                    if(!concreteGenericArg(resolved))fail("E_GENERIC_ARGS","generic arguments must be concrete",l);
                    const auto& constraint=templ.generics[i].constraint;
                    const bool admitted=builtinGenericConstraint(constraint)
                        ? genericConstraintAccepts(constraint,resolved)
                        : traitImplementations.count(constraintTraitKey(templ.module,constraint,l)+"|"+canonicalTypeIdentity(resolved))!=0;
                    if(!admitted)fail("E_GENERIC_CONSTRAINT","type "+typeName(args[i])+" does not satisfy "+constraint,l);
                    sub[templ.generics[i].name]=bindGenericArgumentToTemplateModule(resolved,templ.module,l);
                    if(i)signature+=",";
                    signature+=canonicalTypeIdentity(resolved);
                }
                signature+=">";
                auto found=enumSpecialization.find(signature); if(found!=enumSpecialization.end())return found->second;
                { ++recordSpecializations; budgetCheck("la especializacion generica"); }
                EnumDef g=templ; g.generics.clear(); g.key.clear();
                g.name=templ.name+"__g_"+sha256(signature).substr(0,16);
                for(auto& v:g.variants)if(v.hasPayload)v.payload=substituteGenericType(v.payload,sub,v.loc);
                enumSpecialization[signature]=g.name;
                generatedEnums.push_back(std::move(g));
                genericEnums.emplace(generatedEnums.back().module+"."+generatedEnums.back().name,&generatedEnums.back());
                return generatedEnums.back().name;
            };
            std::function<void(Type&,const std::string&,Loc)> rewriteRecordType;
            rewriteRecordType=[&](Type& t,const std::string& mod,Loc l){
                for(auto& part:t.parts)rewriteRecordType(part,mod,l);
                // CP-02: Resource<Vec<u32>> / Borrow<Vec<u32>> / BorrowMut<Vec<u32>> name an instance of a generic struct as a nominal resource.
                const bool nominalUse=t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::BorrowMut;
                if((t.kind!=Type::Record&&!nominalUse)||t.parts.empty())return;
                std::string targetModule=mod,shortName=t.name,prefix;
                const auto dot=t.name.find('.');
                if(dot!=std::string::npos){
                    prefix=t.name.substr(0,dot); shortName=t.name.substr(dot+1);
                    if(prefix!=mod){
                        auto mi=modules.find(mod);bool ok=false;
                        if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==prefix){targetModule=im.target;ok=true;break;}
                        if(!ok)fail("E_IMPORT","alias no importado en tipo generico: "+prefix,l);
                    }
                }
                const auto templateKey=genericKeyFor(targetModule,shortName);
                auto it=recordTemplates.find(templateKey);
                std::string mangled;
                if(it!=recordTemplates.end()){
                    if(targetModule!=mod&&!it->second->pub)fail("E_VISIBILITY","generic struct is private: "+t.name,l);
                    mangled=instantiateRecord(*it->second,t.parts,l,mod);
                } else {
                    auto et=enumTemplates.find(templateKey);
                    if(et==enumTemplates.end())fail("E_GENERIC_TARGET","type arguments supplied to non-generic type: "+t.name,l);
                    if(targetModule!=mod&&!et->second->pub)fail("E_VISIBILITY","generic enum is private: "+t.name,l);
                    mangled=instantiateEnum(*et->second,t.parts,l,mod);
                }
                t.name=prefix.empty()?mangled:prefix+"."+mangled;
                t.parts.clear();
            };
            std::function<void(std::vector<Stmt>&,const std::string&)> rewriteRecordBlock;
            std::function<void(Expr&,const std::string&)> rewriteRecordExpr,enumConstructorRewrite,traitMethodRewrite;
            // Generic enum constructor: [alias.]Enum.Variant<args>(payload) -> Mangled.Variant(payload).
            // Shared by the struct/enum specialization pass and by scanExpr (generated function bodies reach it first).
            enumConstructorRewrite=[&](Expr& e,const std::string& mod){
                if(e.kind!=Expr::Call||e.typeArgs.empty())return;
                const auto lastDot=e.text.rfind('.');
                if(lastDot==std::string::npos)return;
                const auto head=e.text.substr(0,lastDot),variantName=e.text.substr(lastDot+1);
                std::string target=mod,shortName=head; bool resolvable=true;
                const auto headDot=head.find('.');
                if(headDot!=std::string::npos){
                    const auto prefix=head.substr(0,headDot); shortName=head.substr(headDot+1);
                    if(prefix!=mod){
                        resolvable=false; auto mi=modules.find(mod);
                        if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==prefix){target=im.target;resolvable=true;break;}
                    }
                }
                if(resolvable&&enumTemplates.count(genericKeyFor(target,shortName))){
                    Type use(Type::Record); use.name=head; use.parts=e.typeArgs;
                    rewriteRecordType(use,mod,e.loc); e.text=use.name+"."+variantName; e.typeArgs.clear();
                }
            };
            // Trait method call: [alias.]Trait.method<Type>(args) -> method__impl_<hash>(args), resolved statically.
            traitMethodRewrite=[&](Expr& e,const std::string& mod){
                if(e.kind!=Expr::Call||e.typeArgs.size()!=1)return;
                const auto lastDot=e.text.rfind('.');
                if(lastDot==std::string::npos)return;
                const auto head=e.text.substr(0,lastDot),method=e.text.substr(lastDot+1);
                std::string target=mod,shortName=head,prefix; bool resolvable=true;
                const auto headDot=head.find('.');
                if(headDot!=std::string::npos){
                    prefix=head.substr(0,headDot); shortName=head.substr(headDot+1);
                    if(prefix!=mod){
                        resolvable=false; auto mi=modules.find(mod);
                        if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==prefix){target=im.target;resolvable=true;break;}
                    }
                }
                const auto traitKey=genericKeyFor(target,shortName);
                if(!resolvable||!traits.count(traitKey))return;
                if(target!=mod&&!traits.at(traitKey)->pub)fail("E_VISIBILITY","trait privado: "+head,e.loc);
                auto self=resolveGenericArgument(e.typeArgs[0],mod,e.loc);
                if(!concreteGenericArg(self))fail("E_GENERIC_ARGS","el tipo de un metodo de trait debe ser concreto",e.loc);
                bool declared=false; for(const auto& tm:traits.at(traitKey)->methods)if(tm.name==method)declared=true;
                if(!declared)fail("E_TRAIT_METHOD","el trait "+shortName+" no declara el metodo "+method,e.loc);
                auto it=traitMethodImpl.find(traitKey+"|"+canonicalTypeIdentity(self)+"|"+method);
                if(it==traitMethodImpl.end())fail("E_TRAIT","no hay impl de "+shortName+" para "+typeName(e.typeArgs[0]),e.loc);
                e.generatedReference=true;
                const auto implKey=it->second,implModule=implKey.substr(0,implKey.find('.')),implName=implKey.substr(implKey.find('.')+1);
                if(implModule==mod)e.text=implName;
                else {
                    std::string via; auto mi2=modules.find(mod);
                    if(mi2!=modules.end())for(const auto& im:mi2->second->imports)if(im.target==implModule){via=im.alias;break;}
                    e.text=via.empty()?implKey:via+"."+implName;   // no import: the canonical key of a compiler-generated impl function
                }
                e.typeArgs.clear();
            };
            rewriteRecordExpr=[&](Expr& e,const std::string& mod){
                rewriteRecordType(e.annotation,mod,e.loc);
                enumConstructorRewrite(e,mod);
                traitMethodRewrite(e,mod);
                if(e.kind==Expr::RecordInit){
                    if(!e.typeArgs.empty()){
                        Type use(Type::Record); use.name=e.text; use.parts=e.typeArgs;
                        rewriteRecordType(use,mod,e.loc); e.text=use.name; e.typeArgs.clear();
                    } else {
                        std::string target=mod,shortName=e.text;
                        const auto dot=e.text.find('.');
                        if(dot!=std::string::npos){
                            const auto prefix=e.text.substr(0,dot); shortName=e.text.substr(dot+1);
                            if(prefix!=mod){ auto mi=modules.find(mod); if(mi!=modules.end())for(const auto& im:mi->second->imports)if(im.alias==prefix)target=im.target; }
                        }
                        if(recordTemplates.count(genericKeyFor(target,shortName)))fail("E_GENERIC_ARGS","generic struct requires explicit type arguments: "+e.text,e.loc);
                    }
                } else for(auto& t:e.typeArgs)rewriteRecordType(t,mod,e.loc);
                for(auto& cp:e.closureParams)rewriteRecordType(cp.type,mod,cp.loc);
                for(auto& a:e.args)rewriteRecordExpr(a,mod);
                if(e.closureBody)rewriteRecordBlock(*e.closureBody,mod);
            };
            rewriteRecordBlock=[&](std::vector<Stmt>& b,const std::string& mod){
                for(auto& s:b){
                    rewriteRecordType(s.declared,mod,s.loc);
                    rewriteRecordExpr(s.expr,mod);
                    rewriteRecordBlock(s.body,mod); rewriteRecordBlock(s.other,mod);
                    for(auto& arm:s.arms)rewriteRecordBlock(arm,mod);
                }
            };
            // Moves the generic struct/enum instances created so far into the program so that later lookups (resolveGenericArgument) can find them.
            auto flushGeneratedTypes=[&](){
                if(!generatedEnums.empty()){
                    for(auto& g:generatedEnums)p.enums.push_back(std::move(g));
                    generatedEnums.clear();
                    genericEnums.clear();
                    for(const auto& e:p.enums)genericEnums.emplace(e.module+"."+e.name,&e);
                    budgetCheck("la especializacion generica");
                }
                if(!generatedRecords.empty()){
                    for(auto& g:generatedRecords)p.records.push_back(std::move(g));
                    generatedRecords.clear();
                    genericRecords.clear();
                    for(const auto& r:p.records)genericRecords.emplace(r.module+"."+r.name,&r);
                    budgetCheck("la especializacion generica");
                }
            };
            auto specializeRecords=[&](){
                for(auto& f:p.functions){
                    for(auto& a:f.params)rewriteRecordType(a.type,f.module,a.loc);
                    rewriteRecordType(f.result,f.module,f.loc);
                    rewriteRecordBlock(f.body,f.module);
                }
                for(auto& r:p.records)for(auto& f:r.fields)rewriteRecordType(f.type,r.module,f.loc);
                for(auto& e:p.enums)for(auto& v:e.variants)if(v.hasPayload)rewriteRecordType(v.payload,e.module,v.loc);
                for(auto& d:p.traitImpls)rewriteRecordType(d.forType,d.module,d.loc);
                // Specializations may themselves mention further generic structs: drain until stable.
                for(size_t i=0;i<generatedRecords.size()||i<generatedEnums.size();++i){
                    if(i<generatedRecords.size())for(auto& f:generatedRecords[i].fields)rewriteRecordType(f.type,generatedRecords[i].module,f.loc);
                    if(i<generatedEnums.size())for(auto& v:generatedEnums[i].variants)if(v.hasPayload)rewriteRecordType(v.payload,generatedEnums[i].module,v.loc);
                }
                flushGeneratedTypes();
            };
            specializeRecords();
            scanExpr=[&](Expr& e,const std::string& callerModule){
                for(auto& a:e.args)scanExpr(a,callerModule);
                enumConstructorRewrite(e,callerModule);   // CP-05: generated bodies carry concrete Enum.Variant<args>(..)
                traitMethodRewrite(e,callerModule);       // CP-05b: ... and concrete Trait.method<Type>(..)
                if(e.kind!=Expr::Call)return;
                if(auto* templ=resolveGenericTemplate(modules,templates,callerModule,e.text,e.loc)){
                    if(e.typeArgs.empty())fail("E_GENERIC_ARGS","generic call requires explicit type arguments: "+e.text,e.loc);
                    e.genericTarget=instantiate(*templ,e.typeArgs,e.loc,callerModule);
                    ensureCanonicalGeneratedCallImport(callerModule,templ->module,e.loc);
                } else if(!e.typeArgs.empty()&&!(e.text.rfind("simd.",0)==0&&e.typeArgs.size()<=2)&&!(e.typeArgs.size()==1&&(e.text=="layout.size"||e.text=="layout.align"||e.text=="layout.offset"||e.text=="layout.identity"||e.text=="raw.read"||e.text=="raw.write"||e.text=="slots.alloc"||e.text=="slots.state"||e.text=="slots.gen"||e.text=="slots.put"||e.text=="slots.take"||e.text=="slots.borrow"||e.text=="slots.borrow_mut"))) fail("E_GENERIC_TARGET","type arguments supplied to non-generic call: "+e.text,e.loc);
            };
            scanBlock=[&](std::vector<Stmt>& b,const std::string& callerModule){ for(auto& s:b){scanExpr(s.expr,callerModule);scanBlock(s.body,callerModule);scanBlock(s.other,callerModule);for(auto& a:s.arms)scanBlock(a,callerModule);} };
            for(auto& f:p.functions)scanBlock(f.body,f.module);
            // CP-05: a generated body can call another generic with an instance of a generic struct built from its own parameter (`id<Plain<U>>` inside `relay<U>`);
            // its struct uses are specialized, and the new instances made visible, before the calls inside it are instantiated.
            for(size_t i=0;i<generationOrder.size();++i){ auto& g=generatedByKey.at(generationOrder[i]); rewriteRecordBlock(g.body,g.module); scanBlock(g.body,g.module); }
            for(auto& k:generationOrder)p.functions.push_back(std::move(generatedByKey.at(k)));
            specializeRecords();   // CP-05: generated functions may carry generic struct uses with concrete arguments
        }
        enum class OwnershipClass:uint8_t { Copy, Move, Resource };
        enum class OwnershipState:uint8_t { Uninitialized, Live, Moved, Dropped };
        struct OwnershipEntry {
            Type type;
            OwnershipClass cls=OwnershipClass::Copy;
            OwnershipState state=OwnershipState::Live;
            bool dropRequired=false;
            bool mustConsume=false;   // nominal Resource or pending sum: explicit discharge, no automatic cleanup
            bool operator==(const OwnershipEntry&) const = default;
        };
        using OwnershipLedger=std::map<int,OwnershipEntry>;
        using ProjectedOwnership=std::map<std::string,OwnershipEntry>;
        enum class ResourceAccessKind:uint8_t { Move, SharedBorrow, ExclusiveBorrow };
        enum class LoanKind:uint8_t { Shared, Exclusive };
        struct Place {
            int root=-1;
            std::vector<int> projections;
        };
        using Origin=int;
        struct Region {
            size_t scopeDepth=0;
        };
        struct Loan {
            int binding=-1;
            Origin origin=-1;
            Place place;
            LoanKind kind=LoanKind::Shared;
            Region region;
            std::string name;
            bool active=true;
            int parent=-1;
            bool suspended=false;
            Loc loc;   // CP-16: where the loan was created, reported as a related location on conflicts
        };
        using LoanLedger=std::map<int,Loan>;

        OwnershipClass ownershipClassOf(const Type& t) {
            if(t.kind==Type::Resource)return OwnershipClass::Resource;
            return OwnershipClass::Copy;
        }
        bool tracksOwnership(const Type& t) { return ownershipClassOf(t)!=OwnershipClass::Copy; }
        bool isNominalResource(const Type& t) { return t.kind==Type::Resource&&t.name!="Buffer"; }
        // A nominal resource is a declared struct with exactly one field that is either a u64 handle (kind 1) or the Resource<Buffer> it wraps (kind 2, CP-02).
        static int nominalInnerKind(const RecordDef& r) {
            if(r.fields.size()!=1)return 0;
            const Type& f=r.fields[0].type;
            if(f.kind==Type::U64)return 1;
            if(f.kind==Type::Resource&&f.name=="Buffer")return 2;
            return 0;
        }
        bool requiresDropObligation(const Type& t) { return ownershipClassOf(t)==OwnershipClass::Resource&&!isNominalResource(t); }

        class Checker  {
            Program&p;
            std::map<std::string,Function*>funcs;
            std::map<std::string,RecordDef*>records;
            std::map<std::string,EnumDef*>enums;
            mutable std::map<std::string,bool> pendingEnumCache;
            std::map<std::string,ModuleInfo*>modules;
            std::vector<std::map<std::string,Binding>>scopes;
            std::set<int>pending;
            // CP-02a: the only call expression allowed to yield a Borrow/BorrowMut (a let initializer).
            const Expr* borrowReturnAllowedFor=nullptr;
            OwnershipLedger ownershipLedger;
            LoanLedger loanLedger;
            // Resource and pending-sum leaves owned through immutable record fields.
            // This is separate from root Resource bindings: a record is not a
            // hidden Resource capability. Each leaf carries the same typed
            // drop/explicit-consumption obligation as its corresponding root binding.
            ProjectedOwnership projectedOwnership;
            struct LoopSnapshot { std::set<int> pending; OwnershipLedger ownership; ProjectedOwnership projected; };
            std::vector<LoopSnapshot> loopStack;
            Function*fn=nullptr;
            Function* signatureFunction=nullptr;
            bool canonicalOk=false;   // true while the signature of a compiler-generated function is being resolved
            size_t nodes=0,frameSlots=0;
            std::map<std::string,size_t>widths,heights;
            std::set<std::string>visiting;
            std::vector<Function> generatedClosures;
            uint32_t nextClosure=0;
            bool collectingClosureCaptures=false;
            Type closureResultType;
            size_t closureOuterScopeCount=0;
            std::vector<Binding> closureCaptureValues;
            std::vector<std::string> closureCaptureNames;
            // A85 handles are lexical capabilities to observe one child, not
            // serializable values or authority.  The stack mirrors task_scope.
            std::vector<std::set<int>> taskScopes;
            std::set<int> closedChannels;
            bool transferable(const Type& t) const {
                if(isInteger(t)||isFloat(t)||t.kind==Type::Bool||t.kind==Type::Char||t.kind==Type::Text||t.kind==Type::Bytes)return true;
                if(t.kind==Type::Tuple||t.kind==Type::Array) { for(const auto& part:t.parts)if(!transferable(part))return false; return true; }
                return false;
            }
            std::string placeKey(const Place& place) const {
                std::string key=std::to_string(place.root);
                for(const auto projection:place.projections)key+="."+std::to_string(projection);
                return key;
            }
            void collectOwnershipLeaves(const Type& t,std::vector<int>& path,std::vector<std::vector<int>>& out) const {
                if(!typeContainsResource(p,t,p.module)&&!containsPending(t))return;
                if(t.kind==Type::Resource||isPendingType(t)){
                    out.push_back(path); return;
                }
                if(t.kind==Type::Tuple){
                    for(size_t i=0;i<t.parts.size();++i){
                        path.push_back(static_cast<int>(i));collectOwnershipLeaves(t.parts[i],path,out);path.pop_back();
                    }
                    return;
                }
                if(t.kind==Type::Array){
                    for(uint32_t i=0;i<t.extent;++i){
                        path.push_back(static_cast<int>(i));collectOwnershipLeaves(t.parts.at(0),path,out);path.pop_back();
                    }
                    return;
                }
                if(t.kind!=Type::Record)return;
                const auto record=records.find(t.key);
                if(record==records.end())fail("E_INTERNAL","record sin definicion durante analisis de Place");
                for(size_t i=0;i<record->second->fields.size();++i){
                    path.push_back(static_cast<int>(i));
                    collectOwnershipLeaves(record->second->fields[i].type,path,out);
                    path.pop_back();
                }
            }
            bool containsOwnershipLeaves(const Type& t) const {
                std::vector<std::vector<int>> leaves; std::vector<int> path;
                collectOwnershipLeaves(t,path,leaves);
                return !leaves.empty();
            }
            Type projectedType(const Type& base,int index) const {
                if(index<0)fail("E_INTERNAL","indice de Place negativo");
                if(base.kind==Type::Tuple)return base.parts.at(static_cast<size_t>(index));
                if(base.kind==Type::Array){
                    if(static_cast<uint32_t>(index)>=base.extent)fail("E_INTERNAL","indice de Place Array fuera de rango");
                    return base.parts.at(0);
                }
                if(base.kind==Type::Record)return records.at(base.key)->fields.at(static_cast<size_t>(index)).type;
                fail("E_INTERNAL","proyeccion fuera de un producto probado");
            }
            // CP-01 (OWNERSHIP_COMPOSITION_CANDIDATE.md): an Array whose element owns a Resource or a pending sum is an owning
            // product like Tuple. It is bounded so every element stays an individually tracked Place.
            static constexpr uint32_t kOwningArrayLimit=16;
            void requireOwnedTupleVersion(const Type& t,const std::string& mod,Loc l){
                if((t.kind!=Type::Tuple&&t.kind!=Type::Array)||(!typeContainsResource(p,t,mod)&&!typeContainsPending(p,t,mod)))return;
                if(t.kind==Type::Array&&t.extent>kOwningArrayLimit)fail("E_LIMIT","Array owning admite como maximo 16 elementos",l);
                if(p.representationVersion<21)fail("E_VERSION",std::string(t.kind==Type::Array?"Array":"Tuple")+" owning requiere Wave21/OMC21",l);
                auto* context=signatureFunction?signatureFunction:fn;
                if(context)context->requiresOwnedTupleFence=true;
            }
            void initializeProjectedOwnership(int root,const Type& t){
                if(t.kind!=Type::Record&&t.kind!=Type::Tuple&&t.kind!=Type::Array)return;
                std::vector<std::vector<int>> leaves; std::vector<int> path;
                collectOwnershipLeaves(t,path,leaves);
                for(const auto& leaf:leaves){
                    Type field=t;
                    for(const auto index:leaf)field=projectedType(field,index);
                    const bool pendingField=isPendingType(field);
                    projectedOwnership[placeKey(Place{root,leaf})]=OwnershipEntry{
                        field,pendingField?OwnershipClass::Move:ownershipClassOf(field),OwnershipState::Live,
                        requiresDropObligation(field),pendingField||isNominalResource(field)};
                }
            }
            void requireProjectedDischarged(int root,Loc l) const {
                const auto prefix=std::to_string(root)+".";
                for(const auto& kv:projectedOwnership){
                    if(kv.first.rfind(prefix,0)!=0)continue;
                    requireNominalDischarged(kv.second,l);
                    if(kv.second.dropRequired&&kv.second.state==OwnershipState::Live)requireAutomaticCleanupVersion(l);
                }
            }
            void eraseProjectedOwnership(int root){
                const auto prefix=std::to_string(root)+".";
                for(auto it=projectedOwnership.begin();it!=projectedOwnership.end();)
                    if(it->first.rfind(prefix,0)==0)it=projectedOwnership.erase(it); else ++it;
            }
            void visit(int d,Loc l) {
                if(d>OMNI_LIMIT_EXPR_HEIGHT)fail("E_LIMIT","IR excede limites estructurales",l);
                if((++nodes&1023u)==0u)budgetCheck("el comprobador");
            }
            bool generatedTypeAccess(const std::string& name) const {
                const auto* context=signatureFunction?signatureFunction:fn;
                return context&&context->generated&&context->generatedTypeKeys.count(name)!=0;
            }
            bool generatedTarget(const std::string& name) const {
                for(const auto& f:p.functions)if(f.module+"."+f.name==name)return f.generated;
                return false;
            }
            std::string key(const std::string&name,const std::string&mod,Loc l,bool generatedReference=false) {
                if(!validQualified(name))fail("E_NAME","nombre cualificado invalido: "+name,l);
                auto dot=name.find('.');
                if(dot==std::string::npos)return mod+"."+name;
                auto a=name.substr(0,dot);
                if(a==mod)return name;
                auto mi=modules.at(mod);
                for(auto&im:mi->imports)if(im.alias==a)return im.target+name.substr(dot);
                if(modules.count(a)&&((generatedReference&&generatedTarget(name))||generatedTypeAccess(name)))return name;   // compiler-generated reference
                fail("E_IMPORT","alias no importado: "+a,l);
            }
            // Nominal resource (Core candidate FRAME-RESOURCE-001): Resource<R> / Borrow<R> / BorrowMut<R> where R is a declared,
            // visible struct with exactly one u64 field. The handle is that field. Only the module that declares R can seal/unseal/peek.
            Type resolveNominal(Type t,const std::string&mod,Loc l) {
                std::string k;
                if(!t.key.empty()&&records.count(t.key))k=t.key; else k=key(t.name,mod,l);
                auto ri=records.find(k);
                if(ri==records.end())fail("E_RESOURCE_TYPE","Resource<"+t.name+">: solo Buffer o un struct declarado de un campo u64",l);
                // A generic instance may name the resource its argument stands for even when that struct is private to the caller's module: the argument was validated
                // where the instance was requested (generatedTypeKeys), and seal/unseal/peek/inner stay private to the declaring module.
                if(ri->second->module!=mod&&!ri->second->pub&&!generatedTypeAccess(k))fail("E_VISIBILITY","struct privado: "+t.name,l);
                if(nominalInnerKind(*ri->second)==0)
                    fail("E_RESOURCE_TYPE","recurso nominal requiere un struct con exactamente un campo u64 o Resource<Buffer>: "+t.name,l);
                t.name=k; t.key=k;
                return t;
            }
            Type resolve(Type t,const std::string&mod,Loc l,int d=0) {
                if(d>OMNI_LIMIT_TYPE_DEPTH)fail("E_LIMIT","tipo demasiado profundo",l);
                if(t.kind==Type::Record||t.kind==Type::Enum) {
                    t.key=key(t.name,mod,l);
                    auto ri=records.find(t.key);
                    auto ei=enums.find(t.key);
                    if(ri!=records.end()) {
                        t.kind=Type::Record;
                        const bool generatedBody=generatedTypeAccess(t.key);
                        if(ri->second->module!=mod&&!ri->second->pub&&!generatedBody)fail("E_VISIBILITY","struct privado: "+t.name,l);
                    } else if(ei!=enums.end()) {
                        t.kind=Type::Enum;
                        if(ei->second->module!=mod&&!ei->second->pub&&!generatedTypeAccess(t.key))fail("E_VISIBILITY","enum privado: "+t.name,l);
                    } else fail("E_TYPE","tipo inexistente: "+t.name,l);
                }
                else if(t.kind==Type::Result) {
                    if(t.parts.size()!=2)fail("E_TYPE","Result requiere dos tipos",l);
                    for(auto&a:t.parts) {
                        a=resolve(a,mod,l,d+1);
                        if(a.kind==Type::Borrow||a.kind==Type::BorrowMut||a.kind==Type::View)fail("E_TYPE","Result con borrow/View no admitido",l);
                    }
                }
                else if(t.kind==Type::Option) {
                    if(t.parts.size()!=1)fail("E_TYPE","Option requiere un tipo",l);
                    t.parts[0]=resolve(t.parts[0],mod,l,d+1);
                    auto k=t.parts[0].kind;
                    if(k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::View)fail("E_TYPE","Option de borrow/async/View no admitido en Omni Language 0.2",l);
                }
                else if(t.kind==Type::Tuple) {
                    if(t.parts.size()>16)fail("E_LIMIT","Tuple demasiado grande",l);
                    for(auto& a:t.parts){ a=resolve(a,mod,l,d+1); auto k=a.kind; if(k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::View)fail("E_PRODUCT_LINEAR","Tuple no admite Borrow/async/View sin prueba de vida",l); }
                    requireOwnedTupleVersion(t,mod,l);
                }
                else if(t.kind==Type::Array) {
                    if(t.parts.size()!=1)fail("E_TYPE","Array requiere un tipo de elemento",l);
                    if(t.extent>65535)fail("E_LIMIT","Array demasiado grande",l);
                    t.parts[0]=resolve(t.parts[0],mod,l,d+1);
                    auto k=t.parts[0].kind; if(k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::View)fail("E_PRODUCT_LINEAR","Array no admite Borrow/async/View sin prueba de vida",l);
                    requireOwnedTupleVersion(t,mod,l);
                }
                else if(t.kind==Type::View) {
                    if(t.parts.size()!=1)fail("E_TYPE","View requiere un tipo de elemento",l);
                    t.parts[0]=resolve(t.parts[0],mod,l,d+1);
                    auto k=t.parts[0].kind;
                    if(k==Type::Resource||k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::Result||k==Type::View)
                        fail("E_TYPE","View<T> requiere elemento no lineal/no async/no View",l);
                }
                else if(t.kind==Type::Range) {
                    if(t.parts.size()!=1)fail("E_TYPE","Range requiere un tipo",l);
                    t.parts[0]=resolve(t.parts[0],mod,l,d+1);
                    if(t.parts[0].kind!=Type::U32)fail("E_RANGE_TYPE","Range ejecutable de 0.8.1 requiere u32",l);
                }
                else if(t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::BorrowMut) {
                    if(t.name!="Buffer")t=resolveNominal(t,mod,l);
                }
                else if(t.kind==Type::Future||t.kind==Type::Stream) {
                    fail("E_ASYNC_UNSUPPORTED","Future/Stream estan reservados pero no tienen semantica ejecutable general en 0.2",l);
                }
                else if(t.kind==Type::Param) fail("E_GENERIC_INTERNAL","unresolved generic type parameter: "+t.name,l);
                else if(!isInteger(t)&&!isFloat(t)&&t.kind!=Type::Bool&&t.kind!=Type::Char&&t.kind!=Type::Text&&t.kind!=Type::Bytes&&t.kind!=Type::Range)fail("E_TYPE","tipo no soportado",l);
                return t;
            }
            size_t width(const Type&t,int d=0) {
                if(d>OMNI_LIMIT_LAYOUT_DEPTH)fail("E_LIMIT","layout demasiado profundo");
                if(isInteger(t)||isFloat(t)||t.kind==Type::Bool||t.kind==Type::Char)return 1;
                if(t.kind==Type::Text||t.kind==Type::Bytes)return 2;
                if(t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::BorrowMut)return 1;
                if(t.kind==Type::View)return 2;
                if(t.kind==Type::Range)return 3;
                if(t.kind==Type::Future) {
                    if(t.parts.size()!=1)fail("E_TASK_HANDLE","Future requiere un tipo de resultado");
                    return width(t.parts[0],d+1);
                }
                if(t.kind==Type::Stream) {
                    if(t.parts.size()!=1)fail("E_CHANNEL_TYPE","Stream requiere un tipo de elemento");
                    return 1;
                }
                if(t.kind==Type::Result)return 1+width(t.parts[0],d+1)+width(t.parts[1],d+1);
                if(t.kind==Type::Option)return 1+width(t.parts[0],d+1);
                if(t.kind==Type::Tuple){ size_t n=0; for(auto&a:t.parts){ n+=width(a,d+1); } return n; }
                if(t.kind==Type::Array){ auto ew=width(t.parts.at(0),d+1); return ew*t.extent; }
                auto k=t.key;
                if(widths.count(k)) {
                    if(size_t(d)+heights.at(k)>size_t(OMNI_LIMIT_LAYOUT_DEPTH))fail("E_LIMIT","layout demasiado profundo");
                    return widths[k];
                }
                if(!visiting.insert(k).second)fail("E_LAYOUT_CYCLE","tipo por valor recursivo: "+k);
                size_t n=0,h=1;
                if(t.kind==Type::Record) {
                    for(auto&f:records.at(k)->fields) {
                        n+=width(f.type,d+1);
                        if((f.type.kind==Type::Record||f.type.kind==Type::Enum)&&heights.count(f.type.key))h=std::max(h,1+heights.at(f.type.key));
                    }
                } else if(t.kind==Type::Enum) {
                    n=1; // discriminant
                    for(auto&v:enums.at(k)->variants) if(v.hasPayload) {
                        n+=width(v.payload,d+1);
                        if((v.payload.kind==Type::Record||v.payload.kind==Type::Enum)&&heights.count(v.payload.key))h=std::max(h,1+heights.at(v.payload.key));
                    }
                } else fail("E_INTERNAL","layout nominal desconocido");
                if(size_t(d)+h>size_t(OMNI_LIMIT_LAYOUT_DEPTH))fail("E_LIMIT","layout demasiado profundo");
                heights[k]=h;
                visiting.erase(k);
                widths[k]=n;
                return n;
            }
            void publicType(const Type&t,Loc l) {
                if(t.kind==Type::Record&&!records.at(t.key)->pub)fail("E_VISIBILITY","firma publica expone struct privado",l);
                if(t.kind==Type::Enum&&!enums.at(t.key)->pub)fail("E_VISIBILITY","firma publica expone enum privado",l);
                for(auto&a:t.parts)publicType(a,l);
            }
            std::pair<EnumDef*,int> enumConstructor(const std::string& q,const std::string& mod,Loc l) {
                std::vector<std::string> parts; size_t b=0;
                while(b<=q.size()){ auto d=q.find('.',b); parts.push_back(q.substr(b,d==std::string::npos?std::string::npos:d-b)); if(d==std::string::npos)break; b=d+1; }
                if(parts.size()!=2&&parts.size()!=3)return {nullptr,-1};
                std::string target=mod, en, vn;
                if(parts.size()==2){ en=parts[0]; vn=parts[1]; }
                else {
                    auto alias=parts[0]; en=parts[1]; vn=parts[2];
                    if(alias!=mod){ bool found=false; for(auto&i:modules.at(mod)->imports)if(i.alias==alias){target=i.target;found=true;break;} if(!found)return {nullptr,-1}; }
                }
                auto it=enums.find(target+"."+en); if(it==enums.end())return {nullptr,-1};
                if(target!=mod&&!it->second->pub)fail("E_VISIBILITY","enum privado: "+en,l);
                for(size_t i=0;i<it->second->variants.size();++i)if(it->second->variants[i].name==vn)return {it->second,static_cast<int>(i)};
                fail("E_MATCH_VARIANT","variante inexistente: "+q,l);
            }
            // CP-01: all admitted sums derive the same recursive pending law.
            // Match transfers only the selected payload's obligation to its binder.
            bool isLinearEnum(const Type& t) const {
                if(t.kind!=Type::Enum)return false;
                if(!t.key.empty())if(const auto found=pendingEnumCache.find(t.key);found!=pendingEnumCache.end())return found->second;
                const bool owned=typeRequiresConsumption(p,t,p.module);
                if(!t.key.empty())pendingEnumCache[t.key]=owned;
                return owned;
            }
            // Owning or pending Option payloads carry one outer obligation;
            // only the selected match payload owns its cleanup/consumption.
            bool isLinearOption(const Type& t) const {
                return t.kind==Type::Option&&typeRequiresConsumption(p,t,p.module);
            }
            bool isPendingType(const Type& t) const { return t.kind==Type::Result||isLinearOption(t)||isLinearEnum(t); }
            bool containsPending(const Type& t) const {
                return typeContainsPending(p,t,p.module);
            }
            Binding lookup(const std::string&s,Loc l) {
                for(auto i=scopes.rbegin(); i!=scopes.rend(); ++i) {
                    auto b=i->find(s);
                    if(b!=i->end()){
                        const auto value=b->second;
                        // Every free-place access passes here, including field
                        // bases, borrow/move and assignment targets (not only Ref).
                        if(collectingClosureCaptures&&bindingScope(value.id)<closureOuterScopeCount){
                            if(!closureCaptureAllowed(value))
                                fail("E_CLOSURE_CAPTURE","closure solo admite captura inmutable por valor de Copy: "+s,l);
                            if(std::find(closureCaptureNames.begin(),closureCaptureNames.end(),s)==closureCaptureNames.end()){
                                closureCaptureNames.push_back(s);closureCaptureValues.push_back(value);
                            }
                        }
                        return value;
                    }
                }
                // Suggest only a unique in-scope identifier one edit away. This
                // proposes text, never changes lookup or accepts the program.
                auto oneEdit=[](const std::string& a,const std::string& b) {
                    if(a==b||a.size()+1<b.size()||b.size()+1<a.size())return false;
                    size_t i=0,j=0,edits=0;
                    while(i<a.size()&&j<b.size()) {
                        if(a[i]==b[j]){++i;++j;continue;}
                        if(++edits>1)return false;
                        if(a.size()>=b.size())++i;
                        if(b.size()>=a.size())++j;
                    }
                    return edits+(i<a.size()?1u:0u)+(j<b.size()?1u:0u)==1;
                };
                std::set<std::string> suggestions;
                for(const auto& scope:scopes)for(const auto& entry:scope)
                    if(oneEdit(s,entry.first))suggestions.insert(entry.first);
                Error missing("E_UNDEFINED","nombre fuera de alcance: "+s,l.line,l.column);
                missing.source=l.file;
                if(suggestions.size()==1){missing.expected=s;missing.replacement=*suggestions.begin();}
                throw missing;
            }
            size_t bindingScope(int id) const {
                for(size_t i=0;i<scopes.size();++i)
                    for(const auto& item:scopes[i])if(item.second.id==id)return i;
                fail("E_INTERNAL","binding sin scope");
            }
            bool closureCaptureAllowed(const Binding& b) const {
                if(b.mut||tracksOwnership(b.type)||containsPending(b.type)||typeContainsResource(p,b.type,p.module))return false;
                const auto k=b.type.kind;
                return k!=Type::Borrow&&k!=Type::BorrowMut&&k!=Type::View&&
                    k!=Type::Future&&k!=Type::Stream&&k!=Type::Result;
            }
            int declare(const std::string&s,Type t,bool mut,Loc l,bool parameter=false) {
                (void)parameter; // reserved for signature-origin loan rules in later Alpha.8 slices.
                if(!validIdentifier(s))fail("E_NAME","identificador invalido: "+s,l);
                for(auto&sc:scopes)if(sc.count(s))fail("E_DUPLICATE","no se permite redeclarar/sombrear: "+s,l);
                frameSlots+=width(t);
                if(isPendingType(t)&&mut)fail("E_RESULT_MUTABLE","valor lineal pendiente requiere let o parametro; no var: "+typeName(t),l);
                if(t.kind==Type::Resource&&mut)fail("E_RESOURCE_MUTABLE","Resource requiere ownership inmutable; use move/borrow",l);
                std::vector<std::vector<int>> projectedLeaves; std::vector<int> projectedPath;
                collectOwnershipLeaves(t,projectedPath,projectedLeaves);
                if((t.kind==Type::Record||t.kind==Type::Tuple||t.kind==Type::Array)&&!projectedLeaves.empty()&&mut)fail("E_RESOURCE_MUTABLE","producto owning requiere ownership inmutable; use move/borrow",l);
                if(t.kind==Type::View&&mut)fail("E_VIEW_MUTABLE","View<T> es un borrow read-only y requiere let o parametro",l);
                if((t.kind==Type::Borrow||t.kind==Type::BorrowMut)&&mut)fail("E_BORROW_ESCAPE","Borrow/BorrowMut local requiere let; rebinding mutable se difiere",l);
                int id=static_cast<int>(fn->locals.size());
                fn->locals.push_back(t);
                scopes.back()[s]= {
                    t,mut,id
                };
                if(isPendingType(t))pending.insert(id);
                if(tracksOwnership(t))ownershipLedger[id]=OwnershipEntry{t,ownershipClassOf(t),OwnershipState::Live,requiresDropObligation(t),isNominalResource(t)};
                if((t.kind==Type::Record||t.kind==Type::Tuple||t.kind==Type::Array)&&!projectedLeaves.empty())initializeProjectedOwnership(id,t);
                requireOwnedTupleVersion(t,p.module,l);
                return id;
            }
            bool hasCap(const std::string& cap) const { return fn && fn->capabilities.count(cap); }
            void requireCap(const std::string& raw,Loc l) {
                auto cap=canonicalCapability(raw); fn->directCapabilities.insert(cap);
                if(!hasCap(cap)) failSemantic("E_CAPABILITY","falta capability: "+cap,l,nullptr,{},
                    "declared_effect_covers_operation",{"declare_required_effect_or_remove_operation"},false,cap);
            }
            bool placesOverlap(const Place& a,const Place& b) const {
                if(a.root<0||b.root<0||a.root!=b.root)return false;
                const auto common=std::min(a.projections.size(),b.projections.size());
                for(size_t i=0;i<common;++i)
                    if(a.projections[i]!=b.projections[i])return false;
                // Equal paths and a path prefix overlap. Different first proven
                // projections are disjoint; unproved projections never enter Place.
                return true;
            }
            mutable Loc lastConflictLoc;   // set by loanConflicts() when it reports a conflict (CP-16 related location)
            mutable int lastConflictBinding=-1;
            // Where each Resource place was moved/released, for the "moved here" related location of E_RESOURCE_MOVED.
            std::map<std::string,Loc> moveSites;
            [[noreturn]] void failSemantic(const std::string& code,const std::string& message,Loc location,
                    const Place* place,std::vector<RelatedLocation> related,const std::string& constraint,
                    std::vector<std::string> fixClasses,bool conflict=false,const std::string& capability="") const {
                Error error(code,message,location.line,location.column);
                error.source=location.file;
                for(auto& item:related)if(item.loc.line)error.related.push_back(std::move(item));
                DiagnosticSemanticContext context;
                if(fn){
                    context.symbol=fn->key.empty()?fn->module+"."+fn->name:fn->key;
                    context.symbolId=semanticFunctionId(*fn,!fn->generics.empty());
                }
                context.constraint=constraint;
                context.requiredCapability=capability;
                context.fixClasses=std::move(fixClasses);
                if(place){
                    context.placeRoot=place->root;
                    context.projections=place->projections;
                    for(auto scope=scopes.rbegin();scope!=scopes.rend();++scope){
                        for(const auto& [name,binding]:*scope)if(binding.id==place->root){context.owner=name;break;}
                        if(!context.owner.empty())break;
                    }
                }
                if(conflict){
                    const auto loan=loanLedger.find(lastConflictBinding);
                    if(loan!=loanLedger.end()&&loan->second.active){
                        context.loanBinding=loan->second.binding;
                        context.loanOrigin=loan->second.origin;
                        context.loanKind=loan->second.kind==LoanKind::Shared?"shared":"exclusive";
                    }
                }
                error.semanticContext=std::move(context);
                throw error;
            }
            std::vector<RelatedLocation> conflictRelated() const {
                return {RelatedLocation{"conflicting-loan","el prestamo activo que entra en conflicto se creo aqui",lastConflictLoc}};
            }
            std::vector<RelatedLocation> movedRelated(const std::string& key) const {
                auto it=moveSites.find(key);
                if(it==moveSites.end())return {};
                return {RelatedLocation{"moved-here","el recurso se movio o libero aqui",it->second}};
            }
            bool loanConflicts(const Place& target,ResourceAccessKind access,int ignoredBinding=-1) const {
                for(const auto& kv:loanLedger){
                    const auto& loan=kv.second;
                    if(loan.binding==ignoredBinding)continue;
                    if(!loan.active||!placesOverlap(target,loan.place))continue;
                    const bool conflict=access==ResourceAccessKind::Move||access==ResourceAccessKind::ExclusiveBorrow||
                                        (access==ResourceAccessKind::SharedBorrow&&loan.kind==LoanKind::Exclusive);
                    if(conflict){ lastConflictLoc=loan.loc; lastConflictBinding=loan.binding; return true; }
                }
                return false;
            }
            void refreshLoanSuspensions(){
                for(auto&kv:loanLedger)kv.second.suspended=false;
                for(const auto&kv:loanLedger){
                    const auto&child=kv.second;
                    if(!child.active||child.parent<0)continue;
                    auto parent=loanLedger.find(child.parent);
                    if(parent!=loanLedger.end()&&parent->second.active)parent->second.suspended=true;
                }
            }
            void registerLocalLoan(int binding,int sourceBinding,Place suppliedPlace,LoanKind kind,const std::string& name,Loc l){
                if(binding<0||sourceBinding<0)fail("E_INTERNAL","loan local sin binding/origen",l);
                Origin origin=sourceBinding;
                Place place=suppliedPlace;
                int parentBinding=-1;
                auto parent=loanLedger.find(sourceBinding);
                if(parent!=loanLedger.end()){
                    if(!parent->second.active)fail("E_BORROW_EXPIRED","reborrow de loan expirado",l);
                    if(parent->second.suspended)fail("E_BORROW_CONFLICT","reborrow de loan suspendido",l);
                    if(kind==LoanKind::Exclusive&&parent->second.kind==LoanKind::Shared)
                        fail("E_REBORROW_KIND","Borrow compartido no puede reborrow_mut",l);
                    origin=parent->second.origin;
                    place=parent->second.place;
                    parentBinding=parent->second.binding;
                }
                if(loanConflicts(place,kind==LoanKind::Shared?ResourceAccessKind::SharedBorrow:ResourceAccessKind::ExclusiveBorrow,parentBinding))
                    failSemantic("E_BORROW_CONFLICT","loan local entra en conflicto con un prestamo activo sobre el mismo Place",l,&place,conflictRelated(),
                        "no_overlapping_exclusive_loan",{"end_conflicting_loan_or_change_access"},true);
                loanLedger[binding]=Loan{binding,origin,place,kind,Region{scopes.size()},name,true,parentBinding,false,l};
                refreshLoanSuspensions();
            }
            bool exprMentions(const Expr& e,const std::string& name) const {
                if(e.kind==Expr::Ref&&e.text==name)return true;
                for(const auto& a:e.args)if(exprMentions(a,name))return true;
                return false;
            }
            bool stmtMentions(const Stmt& s,const std::string& name) const {
                if(s.kind==Stmt::Assign&&s.name==name)return true;
                if(exprMentions(s.expr,name))return true;
                for(const auto& x:s.body)if(stmtMentions(x,name))return true;
                for(const auto& x:s.other)if(stmtMentions(x,name))return true;
                for(const auto& arm:s.arms)for(const auto& x:arm)if(stmtMentions(x,name))return true;
                return false;
            }
            bool futureMentions(const std::vector<Stmt>& block,size_t next,const std::string& name) const {
                for(size_t i=next;i<block.size();++i)if(stmtMentions(block[i],name))return true;
                return false;
            }
            void retireDeadLoans(const std::vector<Stmt>& block,size_t next,size_t scopeDepth){
                for(auto& kv:loanLedger){
                    auto& loan=kv.second;
                    if(!loan.active||loan.region.scopeDepth!=scopeDepth)continue;
                    if(!futureMentions(block,next,loan.name))loan.active=false;
                }
                refreshLoanSuspensions();
            }
            void eraseScopeLoans(size_t scopeDepth){
                for(auto it=loanLedger.begin();it!=loanLedger.end();){
                    if(it->second.region.scopeDepth==scopeDepth)it=loanLedger.erase(it);
                    else ++it;
                }
                refreshLoanSuspensions();
            }
            bool collectProvenPlace(const Expr& e,Place& out) const {
                if(e.kind==Expr::Ref&&e.binding>=0){ out=Place{e.binding,{}}; return true; }
                const bool field=e.kind==Expr::Field&&e.args.size()==1;
                const bool tuple=e.kind==Expr::Call&&e.text=="tuple.get"&&e.args.size()==2&&e.resolved=="@builtin:tuple.get";
                const bool element=e.kind==Expr::Call&&e.args.size()==2&&e.resolved=="@builtin:array.place";
                if((!field&&!tuple&&!element)||e.binding<0)return false;
                if(!collectProvenPlace(e.args[0],out))return false;
                out.projections.push_back(e.binding);
                return true;
            }
            // `array.get(a, 2u32)` / `a[2u32]` on an owning Array is a Place; any other index of any other array stays a value read.
            bool owningArrayElement(const Expr& e){
                if(e.kind!=Expr::Call||e.args.size()!=2||e.args[1].kind!=Expr::Number||(e.text!="array.get"&&e.text!="index"))return false;
                Type base;
                if(!placeProductType(e.args[0],base)||base.kind!=Type::Array)return false;
                return typeContainsResource(p,base,fn->module)||containsPending(base);
            }
            // An Array reached through a non-Place expression (a call result, `move(...)`) would be dropped without its cleanup obligation.
            void rejectOwningArrayTemporary(const Type& t,Loc l) const {
                if(t.kind==Type::Array&&(typeContainsResource(p,t,fn->module)||containsPending(t)))
                    fail("E_RESOURCE_ACCESS","proyeccion de Array temporal owning requiere propietario ligado",l);
            }
            bool owningArrayPlace(const Expr& base){
                Type t;
                if(!structuralPlace(base)||!placeProductType(base,t)||t.kind!=Type::Array)return false;
                return typeContainsResource(p,t,fn->module)||containsPending(t);
            }
            // Element access on an owning Array: literal indices are individually tracked Places (checked on the owner, never copied);
            // a dynamic index cannot prove which element is read, so it is rejected instead of guessed.
            bool owningArrayIndex(Expr& e,int d,Type& t){
                if(e.args.size()!=2||!owningArrayPlace(e.args[0]))return false;
                if(e.args[1].kind!=Expr::Number)fail("E_ARRAY_OWNING_INDEX","Array owning solo admite indice literal como Place",e.args[1].loc);
                const auto base=provenPlaceType(e.args[0],d+1);
                t=resolveArrayElementPlace(e,base,d);
                checkProjectedValueRead(e,t);
                return true;
            }
            bool structuralPlace(const Expr& e){
                const Expr* current=&e;
                for(int depth=0;depth<=64;++depth){
                    if(current->kind==Expr::Ref)return true;
                    const bool field=current->kind==Expr::Field&&current->args.size()==1;
                    const bool tuple=current->kind==Expr::Call&&current->text=="tuple.get"&&current->args.size()==2&&current->args[1].kind==Expr::Number;
                    if(!field&&!tuple&&!owningArrayElement(*current))return false;
                    current=&current->args[0];
                }
                return false;
            }
            Type resolveRecordField(Expr& e,const Type& base){
                if(e.args.size()!=1||!validIdentifier(e.text))fail("E_IR","proyeccion invalida",e.loc);
                if(base.kind!=Type::Record)fail("E_TYPE","campos requieren un struct",e.loc);
                const auto def=records.at(base.key);
                for(size_t i=0;i<def->fields.size();++i){
                    if(def->fields[i].name!=e.text)continue;
                    e.binding=static_cast<int>(i);
                    e.type=def->fields[i].type;
                    return e.type;
                }
                fail("E_FIELDS","campo inexistente: "+e.text,e.loc);
            }
            Type resolveTupleProjection(Expr& e,const Type& base,int depth){
                if(e.args.size()!=2)fail("E_ARITY","tuple.get requiere tuple e indice literal",e.loc);
                if(base.kind!=Type::Tuple)fail("E_TYPE","tuple.get requiere Tuple",e.loc);
                auto& index=e.args[1];
                if(index.kind!=Expr::Number)fail("E_TUPLE_INDEX","tuple.get requiere indice literal",index.loc);
                need(expr(index,depth+1),Type::U32,index.loc);
                if(index.value>=base.parts.size())fail("E_BOUNDS","indice Tuple fuera de rango",index.loc);
                e.binding=static_cast<int>(index.value);e.resolved="@builtin:tuple.get";
                e.type=base.parts.at(static_cast<size_t>(e.binding));return e.type;
            }
            Type resolveArrayElementPlace(Expr& e,const Type& base,int depth){
                if(e.args.size()!=2)fail("E_ARITY","elemento de Array owning requiere Array e indice literal",e.loc);
                if(base.kind!=Type::Array)fail("E_TYPE","elemento de Array owning requiere Array",e.loc);
                auto& index=e.args[1];
                if(index.kind!=Expr::Number)fail("E_ARRAY_OWNING_INDEX","Array owning solo admite indice literal como Place",index.loc);
                need(expr(index,depth+1),Type::U32,index.loc);
                if(index.value>=base.extent)fail("E_BOUNDS","indice Array fuera de rango",index.loc);
                e.binding=static_cast<int>(index.value);e.resolved="@builtin:array.place";
                e.type=base.parts.at(0);return e.type;
            }
            // Resolve only Ref/Field Places without reading an owning value.
            // Arbitrary expressions must never inherit this permission.
            Type provenPlaceType(Expr& e,int depth){
                visit(depth,e.loc);
                if(e.kind==Expr::Ref){
                    const auto b=lookup(e.text,e.loc);
                    e.binding=b.id; e.type=b.type;
                    return e.type;
                }
                if(e.kind==Expr::Call&&e.text=="tuple.get"&&e.args.size()==2){
                    const auto base=provenPlaceType(e.args[0],depth+1);
                    return resolveTupleProjection(e,base,depth);
                }
                if(owningArrayElement(e)){
                    const auto base=provenPlaceType(e.args[0],depth+1);
                    return resolveArrayElementPlace(e,base,depth);
                }
                if(e.kind!=Expr::Field||e.args.size()!=1)fail("E_PLACE","se requiere un Place estructural probado",e.loc);
                const auto base=provenPlaceType(e.args[0],depth+1);
                return resolveRecordField(e,base);
            }
            void checkProjectedValueRead(Expr& e,const Type& t){
                if(isPendingType(t)){
                    Place place;
                    if(!collectProvenPlace(e,place))fail("E_PLACE","pending requiere un Place probado",e.loc);
                    const auto key=placeKey(place);
                    auto state=projectedOwnership.find(key);
                    if(state==projectedOwnership.end()||state->second.state!=OwnershipState::Live)
                        failRelated("E_RESULT_MOVED","Place pending ya consumido",e.loc,movedRelated(key));
                    if(loanConflicts(place,ResourceAccessKind::Move))
                        failRelated("E_BORROW_CONFLICT","transferencia pending en conflicto con loan activo",e.loc,conflictRelated());
                    state->second.state=OwnershipState::Moved;moveSites[key]=e.loc;
                } else if(typeContainsResource(p,t,fn->module)||containsPending(t))
                    fail("E_RESOURCE_ACCESS","Place owning requiere move(...) o borrow(...); no puede copiarse",e.loc);
            }
            // CP-01b (AGGREGATE_MOVE_CANDIDATE.md): `move(r)` on a struct that owns Resources is rewritten into the
            // construction `R { f: move(r.f) | r.f, ... }` (recursively), so every leaf goes through the proven field-move
            // machinery (liveness, loans, cleanup, evaluator and native lowering) and no new representation is needed.
            bool placeProductType(const Expr& a,Type& out) {
                if(a.kind==Expr::Ref){ out=lookup(a.text,a.loc).type; return true; }
                if(a.kind==Expr::Field&&a.args.size()==1) {
                    Type base;
                    if(!placeProductType(a.args[0],base)||base.kind!=Type::Record)return false;
                    auto def=records.find(base.key);
                    if(def==records.end())return false;
                    for(const auto& field:def->second->fields)if(field.name==a.text){ out=field.type; return true; }
                }
                if(a.kind==Expr::Call&&a.text=="tuple.get"&&a.args.size()==2&&a.args[1].kind==Expr::Number){
                    Type base;
                    if(!placeProductType(a.args[0],base)||base.kind!=Type::Tuple||a.args[1].value>=base.parts.size())return false;
                    out=base.parts.at(static_cast<size_t>(a.args[1].value));return true;
                }
                if(a.kind==Expr::Call&&(a.text=="array.get"||a.text=="index")&&a.args.size()==2&&a.args[1].kind==Expr::Number){
                    Type base;
                    if(!placeProductType(a.args[0],base)||base.kind!=Type::Array||a.args[1].value>=base.extent)return false;
                    out=base.parts.at(0);return true;
                }
                return false;
            }
            bool owningProduct(const Type& part) const {
                return part.kind==Type::Resource||((part.kind==Type::Record||part.kind==Type::Tuple||part.kind==Type::Array)&&containsOwnershipLeaves(part));
            }
            bool expandAggregateMove(Expr& e) {
                Type type;
                if(!placeProductType(e.args[0],type)||(type.kind!=Type::Record&&type.kind!=Type::Tuple&&type.kind!=Type::Array)||!containsOwnershipLeaves(type))return false;
                if(type.kind==Type::Tuple||type.kind==Type::Array){
                    const bool array=type.kind==Type::Array;
                    Expr init;init.kind=Expr::Call;init.loc=e.loc;init.text=array?"array":"tuple";
                    const size_t count=array?type.extent:type.parts.size();
                    for(size_t i=0;i<count;++i){
                        Expr index;index.kind=Expr::Number;index.loc=e.loc;index.value=i;
                        Expr place;place.kind=Expr::Call;place.loc=e.loc;place.text=array?"array.get":"tuple.get";
                        place.args={e.args[0],std::move(index)};
                        const auto& part=array?type.parts.at(0):type.parts[i];
                        if(owningProduct(part)){
                            Expr moved;moved.kind=Expr::Call;moved.loc=e.loc;moved.text="move";moved.args.push_back(std::move(place));
                            init.args.push_back(std::move(moved));
                        } else init.args.push_back(std::move(place));
                    }
                    e=std::move(init);return true;
                }
                const auto* def=records.at(type.key);
                Expr init; init.kind=Expr::RecordInit; init.loc=e.loc; init.text=type.name;
                if(def->module!=fn->module){
                    for(const auto& imported:modules.at(fn->module)->imports){
                        if(imported.target!=def->module)continue;
                        init.text=imported.alias+"."+def->name;
                        break;
                    }
                }
                for(const auto& field:def->fields) {
                    Expr place; place.kind=Expr::Field; place.loc=e.loc; place.text=field.name; place.args.push_back(e.args[0]);
                    const bool owning=owningProduct(field.type);
                    if(owning) {
                        Expr moved; moved.kind=Expr::Call; moved.loc=e.loc; moved.text="move"; moved.args.push_back(std::move(place));
                        init.args.push_back(std::move(moved));
                    } else init.args.push_back(std::move(place));
                    init.names.push_back(field.name);
                }
                e=std::move(init);
                return true;
            }
            Type resourceAccess(Expr& a,ResourceAccessKind access,Loc l){
                const char* op=access==ResourceAccessKind::Move?"move":(access==ResourceAccessKind::SharedBorrow?"borrow":"borrow_mut");
                if(a.kind==Expr::Field||(a.kind==Expr::Call&&a.text=="tuple.get")||owningArrayElement(a)){
                    const auto fieldType=provenPlaceType(a,1);
                    Place place;
                    if(fieldType.kind!=Type::Resource||!collectProvenPlace(a,place))
                        fail("E_PLACE",std::string(op)+" requiere un Place Resource<Buffer> probado",l);
                    a.placeRoot=place.root; a.placePath=place.projections;
                    auto state=projectedOwnership.find(placeKey(place));
                    if(state==projectedOwnership.end()||state->second.state!=OwnershipState::Live)
                        failSemantic("E_RESOURCE_MOVED","Resource de campo ya movido/liberado",l,&place,movedRelated(placeKey(place)),
                            "resource_is_live",{"use_live_owner"});
                    if(loanConflicts(place,access))failSemantic("E_BORROW_CONFLICT",std::string(op)+" entra en conflicto con un loan activo sobre el Place",l,&place,conflictRelated(),
                        "no_overlapping_exclusive_loan",{"end_conflicting_loan_or_change_access"},true);
                    if(access==ResourceAccessKind::Move){ state->second.state=OwnershipState::Moved; moveSites[placeKey(place)]=l; }
                    Type t(access==ResourceAccessKind::Move?Type::Resource:(access==ResourceAccessKind::SharedBorrow?Type::Borrow:Type::BorrowMut));
                    t.name=fieldType.name;
                    return t;
                }
                if(a.kind==Expr::Call&&(a.text=="array.get"||a.text=="index")&&a.args.size()==2&&owningArrayPlace(a.args[0]))
                    fail("E_ARRAY_OWNING_INDEX",std::string(op)+" sobre un Array owning solo admite indice literal como Place",l);
                if(a.kind!=Expr::Ref){
                    if(access!=ResourceAccessKind::Move)fail("E_PLACE",std::string(op)+" requiere un Place probado",l);
                    fail("E_RESOURCE_ACCESS",std::string(op)+" requiere una variable Resource",l);
                }
                auto b=lookup(a.text,a.loc); a.binding=b.id; a.type=b.type;
                a.placeRoot=b.id; a.placePath.clear();
                if(b.type.kind==Type::Borrow||b.type.kind==Type::BorrowMut){
                    if(p.representationVersion<18)
                        fail("E_VERSION","reborrow requiere Wave18/OMC18",l);
                    if(access==ResourceAccessKind::Move)fail("E_RESOURCE_ACCESS","move requiere Resource<T>",l);
                    auto parent=loanLedger.find(b.id);
                    if(parent==loanLedger.end()||!parent->second.active)fail("E_BORROW_EXPIRED","reborrow de loan expirado",l);
                    if(parent->second.suspended)fail("E_BORROW_CONFLICT","reborrow de loan suspendido",l);
                    if(access==ResourceAccessKind::ExclusiveBorrow&&b.type.kind==Type::Borrow)
                        fail("E_REBORROW_KIND","Borrow compartido no puede reborrow_mut",l);
                    Type t(access==ResourceAccessKind::SharedBorrow?Type::Borrow:Type::BorrowMut);
                    t.name=b.type.name;
                    return t;
                }
                if(b.type.kind!=Type::Resource)fail("E_RESOURCE_ACCESS",std::string(op)+" requiere Resource<T>",l);
                auto it=ownershipLedger.find(b.id);
                const Place rootPlace{b.id,{}};
                if(it==ownershipLedger.end()||it->second.state!=OwnershipState::Live)failSemantic("E_RESOURCE_MOVED","Resource ya movido/liberado: "+a.text,l,&rootPlace,movedRelated(std::to_string(b.id)),
                    "resource_is_live",{"use_live_owner"});
                if(loanConflicts(rootPlace,access))failSemantic("E_BORROW_CONFLICT",std::string(op)+" entra en conflicto con un loan activo: "+a.text,l,&rootPlace,conflictRelated(),
                    "no_overlapping_exclusive_loan",{"end_conflicting_loan_or_change_access"},true);
                if(access==ResourceAccessKind::Move){ it->second.state=OwnershipState::Moved; moveSites[std::to_string(b.id)]=l; }
                Type::Kind k=access==ResourceAccessKind::Move?Type::Resource:(access==ResourceAccessKind::SharedBorrow?Type::Borrow:Type::BorrowMut);
                Type t(k); t.name=b.type.name; return t;
            }
            Place loanPlaceForBinding(int binding) const {
                auto it=loanLedger.find(binding);
                if(it!=loanLedger.end()&&it->second.active)return it->second.place;
                return Place{binding,{}};
            }
            // Before argument evaluation, prove structural Places on a copy. Never
            // consume the value, trust serialized bindings or execute an operand.
            bool callAccessPlace(const Expr& operand,Place& place,Type& type){
                if(!structuralPlace(operand))return false;
                Expr checked=operand;
                type=provenPlaceType(checked,1);
                if(!collectProvenPlace(checked,place))return false;
                if(type.kind==Type::Borrow||type.kind==Type::BorrowMut)
                    place=loanPlaceForBinding(place.root);
                return true;
            }
            void collectCallEvaluationAccesses(const Expr& e,std::vector<std::pair<Place,ResourceAccessKind>>& out){
                if(e.kind==Expr::Ref){
                    auto b=lookup(e.text,e.loc);
                    if(b.type.kind==Type::Borrow)out.push_back({loanPlaceForBinding(b.id),ResourceAccessKind::SharedBorrow});
                    else if(b.type.kind==Type::BorrowMut)out.push_back({loanPlaceForBinding(b.id),ResourceAccessKind::ExclusiveBorrow});
                    return;
                }
                if(e.kind==Expr::Call&&(e.text=="tls.get"||e.text=="tls.set")){ for(size_t i=1;i<e.args.size();++i)collectCallEvaluationAccesses(e.args[i],out); return; }
                if(e.kind==Expr::Call&&e.text.rfind("layout.offset",0)==0)return;
                if(e.kind==Expr::Call&&(e.text=="move"||e.text=="borrow"||e.text=="borrow_mut")&&e.args.size()==1){
                    Place place;Type type;
                    if(callAccessPlace(e.args[0],place,type)){
                        const bool owning=typeContainsResource(p,type,fn->module)||containsPending(type);
                        if(owning||type.kind==Type::Borrow||type.kind==Type::BorrowMut){
                            const auto access=e.text=="move"?ResourceAccessKind::Move:(e.text=="borrow"?ResourceAccessKind::SharedBorrow:ResourceAccessKind::ExclusiveBorrow);
                            out.push_back({place,access});
                            return;
                        }
                    }
                }
                for(const auto& a:e.args)collectCallEvaluationAccesses(a,out);
            }
            bool topLevelCallLoan(const Expr& e,Place& place,LoanKind& kind){
                if(e.kind==Expr::Ref){
                    auto b=lookup(e.text,e.loc);
                    if(b.type.kind==Type::Borrow||b.type.kind==Type::BorrowMut){
                        place=loanPlaceForBinding(b.id);
                        kind=b.type.kind==Type::Borrow?LoanKind::Shared:LoanKind::Exclusive;
                        return true;
                    }
                    return false;
                }
                if(e.kind==Expr::Call&&(e.text=="resource.inner"||e.text=="resource.inner_mut")&&e.args.size()==1)
                    return topLevelCallLoan(e.args[0],place,kind);   // the same storage, so the same loan (the stronger kind of the borrow it came from)
                if(e.kind==Expr::Call&&(e.text=="borrow"||e.text=="borrow_mut")&&e.args.size()==1){
                    Type type;
                    if(!callAccessPlace(e.args[0],place,type))return false;
                    if(type.kind!=Type::Resource&&type.kind!=Type::Borrow&&type.kind!=Type::BorrowMut)return false;
                    kind=e.text=="borrow"?LoanKind::Shared:LoanKind::Exclusive;
                    return true;
                }
                return false;
            }
            void validateCallEvaluationOrder(const std::vector<Expr>& args,Loc l){
                std::vector<std::pair<Place,LoanKind>> live;
                for(const auto& arg:args){
                    std::vector<std::pair<Place,ResourceAccessKind>> accesses;
                    collectCallEvaluationAccesses(arg,accesses);
                    for(const auto& access:accesses)for(const auto& earlier:live){
                        if(placesOverlap(access.first,earlier.first)&&
                           (access.second!=ResourceAccessKind::SharedBorrow||earlier.second!=LoanKind::Shared))
                            fail("E_BORROW_CONFLICT","argument evaluation overlaps a live call loan on the same Place",l);
                    }
                    Place place;LoanKind kind=LoanKind::Shared;
                    if(topLevelCallLoan(arg,place,kind))live.push_back({place,kind});
                }
            }
            void validateLoanArguments(const std::vector<Expr>& args,Loc l){
                std::vector<std::pair<Place,ResourceAccessKind>> seen;
                for(const auto& a:args){
                    const bool shared=a.type.kind==Type::Borrow;
                    const bool exclusive=a.type.kind==Type::BorrowMut;
                    const bool moved=a.type.kind==Type::Resource&&a.kind==Expr::Call&&a.resolved=="@builtin:resource.move";
                    if(!shared&&!exclusive&&!moved)continue;
                    Place place;
                    if(a.kind==Expr::Ref)place=loanPlaceForBinding(a.binding);
                    else if(a.placeRoot>=0)place=Place{a.placeRoot,a.placePath};
                    else fail("E_PLACE","call loan requires a checked Place",a.loc);
                    const auto access=shared?ResourceAccessKind::SharedBorrow:(exclusive?ResourceAccessKind::ExclusiveBorrow:ResourceAccessKind::Move);
                    for(const auto& prior:seen)
                        if(placesOverlap(place,prior.first)&&(access!=ResourceAccessKind::SharedBorrow||prior.second!=ResourceAccessKind::SharedBorrow))
                            fail("E_BORROW_CONFLICT","call arguments overlap a live borrow/move on the same Place",l);
                    seen.push_back({place,access});
                }
            }
            void need(const Type&a,const Type&b,Loc l) {
                if(a!=b)fail("E_TYPE","se esperaba "+typeName(b)+", se obtuvo "+typeName(a),l);
            }
            void allHandled(Loc l) {
                if(!pending.empty())fail("E_RESULT_UNHANDLED","Result sin tratar o propagar antes del retorno",l);
            }
            void requireAutomaticCleanupVersion(Loc l) const {
                // A cleanup-bearing program has semantics that did not exist in
                // Wave/OMC 1--17.  The plan is recomputed from the checked AST,
                // but it must never be silently relabelled as historical input.
                if(p.representationVersion<18)
                    fail("E_VERSION","cleanup estructurado requiere Wave18/OMC18",l);
            }
            // Nominal Resources and pending sums require explicit discharge.
            void requireNominalDischarged(const OwnershipEntry& entry,Loc l) const {
                if(entry.mustConsume&&entry.state==OwnershipState::Live&&isPendingType(entry.type))
                    fail("E_RESULT_UNHANDLED","campo pending "+typeName(entry.type)+" debe tratarse antes de salir del alcance",l);
                if(entry.mustConsume&&entry.state==OwnershipState::Live)
                    fail("E_RESOURCE_UNCONSUMED","Resource nominal "+typeName(entry.type)+" debe consumirse explicitamente (move) antes de salir del alcance",l);
            }
            void allOwnedHandled(Loc l) {
                for(const auto& kv:ownershipLedger){
                    const auto& entry=kv.second;
                    requireNominalDischarged(entry,l);
                    if(entry.dropRequired&&entry.state==OwnershipState::Live)
                        requireAutomaticCleanupVersion(l);
                }
                for(const auto& kv:projectedOwnership){
                    requireNominalDischarged(kv.second,l);
                    if(kv.second.dropRequired&&kv.second.state==OwnershipState::Live)
                        requireAutomaticCleanupVersion(l);
                }
            }
            Type expr(Expr&e,int d) {
                visit(d,e.loc);
                Type t;
                switch(e.kind) {
                    case Expr::Number:
                        t=e.annotation.kind==Type::Unknown?Type(Type::U32):resolve(e.annotation,fn->module,e.loc);
                        if(!isInteger(t)&&!isFloat(t))fail("E_NUMBER","literal numerico requiere entero o float",e.loc);
                        if(isInteger(t)&&!positiveLiteralFits(t,e.value))fail("E_OVERFLOW_LITERAL","literal fuera de "+typeName(t),e.loc);
                    break;
                    case Expr::Boolean:if(e.value>1)fail("E_IR","booleano invalido",e.loc);
                    t=Type::Bool;
                    break;
                    case Expr::Text:
                        if(e.text.size()>65536)fail("E_LIMIT","literal Text excede 64 KiB",e.loc);
                        validateUTF8(e.text);
                        t=Type::Text;
                        break;
                    case Expr::Ref: {
                        auto b=lookup(e.text,e.loc);
                        e.binding=b.id;
                        t=b.type;
                        if(t.kind==Type::Resource)fail("E_RESOURCE_ACCESS","Resource requiere move(...) o borrow(...): "+e.text,e.loc);
                        if((t.kind==Type::Record||t.kind==Type::Tuple||t.kind==Type::Array)&&containsOwnershipLeaves(t))
                            fail("E_RESOURCE_ACCESS","producto owning requiere move(...) o proyeccion probada; no puede copiarse",e.loc);
                        if(t.kind==Type::Borrow||t.kind==Type::BorrowMut){
                            auto li=loanLedger.find(b.id);
                            if(li!=loanLedger.end()&&!li->second.active)fail("E_BORROW_EXPIRED","borrow fuera de su region inferida: "+e.text,e.loc);
                            if(li!=loanLedger.end()&&li->second.suspended)fail("E_BORROW_CONFLICT","borrow suspendido durante un reborrow activo: "+e.text,e.loc);
                        }
                        if(isPendingType(t)&&!pending.erase(b.id))fail("E_RESULT_MOVED","Result/Option<Resource>/enum lineal ya consumido: "+e.text,e.loc);
                        if(t.kind==Type::Future)fail("E_TASK_HANDLE_ESCAPE","Future solo puede consumirse por join/cancel dentro de task_scope: "+e.text,e.loc);
                        if(t.kind==Type::Stream)fail("E_CHANNEL_HANDLE_ESCAPE","Stream solo puede usarse por send/receive/close: "+e.text,e.loc);
                        break;
                    }
                    case Expr::Join: {
                        if(taskScopes.empty())fail("E_TASK_SCOPE","join requiere task_scope",e.loc);
                        auto b=lookup(e.text,e.loc);
                        if(b.type.kind!=Type::Future||b.type.parts.size()!=1)fail("E_TASK_HANDLE","join requiere Future abierto: "+e.text,e.loc);
                        bool found=false;
                        for(auto it=taskScopes.rbegin();it!=taskScopes.rend();++it)if(it->erase(b.id)){found=true;break;}
                        if(!found)fail("E_TASK_HANDLE_CONSUMED","Future ya consumido o fuera de su task_scope: "+e.text,e.loc);
                        e.binding=b.id;
                        t=Type(Type::Result); t.parts={b.type.parts[0],Type(Type::U32)};
                        break;
                    }
                    case Expr::Cancel: {
                        if(taskScopes.empty())fail("E_TASK_SCOPE","cancel requiere task_scope",e.loc);
                        auto b=lookup(e.text,e.loc);
                        if(b.type.kind!=Type::Future||b.type.parts.size()!=1)fail("E_TASK_HANDLE","cancel requiere Future abierto: "+e.text,e.loc);
                        bool found=false;
                        for(auto it=taskScopes.rbegin();it!=taskScopes.rend();++it)if(it->erase(b.id)){found=true;break;}
                        if(!found)fail("E_TASK_HANDLE_CONSUMED","Future ya consumido o fuera de su task_scope: "+e.text,e.loc);
                        e.binding=b.id;
                        t=Type(Type::Result); t.parts={Type(Type::U32),Type(Type::U32)};
                        break;
                    }
                    case Expr::Deadline: {
                        if(taskScopes.empty())fail("E_TASK_SCOPE","deadline requiere task_scope",e.loc);
                        auto b=lookup(e.text,e.loc);
                        if(b.type.kind!=Type::Future||b.type.parts.size()!=1)fail("E_TASK_HANDLE","deadline requiere Future abierto: "+e.text,e.loc);
                        if(e.args.size()!=1||e.args[0].kind!=Expr::Number)fail("E_DEADLINE","ticks debe ser literal u32",e.loc);
                        need(expr(e.args[0],d+1),Type::U32,e.loc);
                        bool found=false;
                        for(auto it=taskScopes.rbegin();it!=taskScopes.rend();++it)if(it->erase(b.id)){found=true;break;}
                        if(!found)fail("E_TASK_HANDLE_CONSUMED","Future ya consumido o fuera de su task_scope: "+e.text,e.loc);
                        e.binding=b.id; t=Type(Type::Result); t.parts={b.type.parts[0],Type(Type::U32)};
                        break;
                    }
                    case Expr::Channel: {
                        if(e.annotation.kind!=Type::Stream||e.annotation.parts.size()!=1)fail("E_CHANNEL_TYPE","channel requiere un tipo de elemento",e.loc);
                        auto element=resolve(e.annotation.parts[0],fn->module,e.loc);
                        if(!transferable(element))fail("E_TASK_TRANSFER","channel requiere elemento transferible",e.loc);
                        if(!isInteger(element)&&element.kind!=Type::Text&&element.kind!=Type::Bytes)
                            fail("E_CHANNEL_PROFILE","A85 channel requiere entero, Text o Bytes en el perfil nativo",e.loc);
                        if(e.args.size()!=1||e.args[0].kind!=Expr::Number)fail("E_CHANNEL_CAPACITY","capacity debe ser literal u32",e.loc);
                        need(expr(e.args[0],d+1),Type::U32,e.loc);
                        if(e.args[0].value==0||e.args[0].value>1024)fail("E_CHANNEL_CAPACITY","capacity debe estar entre 1 y 1024",e.loc);
                        t=Type(Type::Stream); t.parts.push_back(element);
                        break;
                    }
                    case Expr::Send: {
                        auto b=lookup(e.text,e.loc);
                        if(b.type.kind!=Type::Stream||b.type.parts.size()!=1)fail("E_CHANNEL_HANDLE","send requiere Stream<T>: "+e.text,e.loc);
                        if(closedChannels.count(b.id))fail("E_CHANNEL_CLOSED","send despues de close: "+e.text,e.loc);
                        if(e.args.size()!=1)fail("E_ARITY","send requiere endpoint y valor",e.loc);
                        need(expr(e.args[0],d+1),b.type.parts[0],e.loc);
                        e.binding=b.id; t=Type(Type::Result); t.parts={Type(Type::U32),Type(Type::U32)};
                        break;
                    }
                    case Expr::Receive: {
                        auto b=lookup(e.text,e.loc);
                        if(b.type.kind!=Type::Stream||b.type.parts.size()!=1)fail("E_CHANNEL_HANDLE","receive requiere Stream<T>: "+e.text,e.loc);
                        e.binding=b.id; Type option(Type::Option); option.parts.push_back(b.type.parts[0]);
                        t=Type(Type::Result); t.parts={option,Type(Type::U32)};
                        break;
                    }
                    case Expr::Try: fail("E_TRY_POSITION","? no se admite en esta posicion (closure, condicion de bucle o contexto no elevable)",e.loc);
                    case Expr::Close: {
                        auto b=lookup(e.text,e.loc);
                        if(b.type.kind!=Type::Stream||b.type.parts.size()!=1)fail("E_CHANNEL_HANDLE","close requiere Stream<T>: "+e.text,e.loc);
                        e.binding=b.id; closedChannels.insert(b.id);
                        t=Type(Type::Result); t.parts={Type(Type::U32),Type(Type::U32)};
                        break;
                    }
                    case Expr::Call: {
                        // A top-level Borrow/BorrowMut argument remains live until the outer call
                        // executes. Validate later argument evaluation against those call-scoped loans.
                        if(e.text!="tls.get"&&e.text!="tls.set"&&e.text.rfind("layout.offset",0)!=0)validateCallEvaluationOrder(e.args,e.loc);   // the first argument of tls.get/tls.set names a thread_local, it is not an expression
                        if(e.text=="u8"||e.text=="u16"||e.text=="u32"||e.text=="u64"||e.text=="i8"||e.text=="i16"||e.text=="i32"||e.text=="i64"||e.text=="f32"||e.text=="f64") {
                            if(e.args.size()!=1)fail("E_ARITY","conversion numerica requiere un argumento",e.loc);
                            auto src=expr(e.args[0],d+1);
                            if(!isInteger(src)&&!isFloat(src))fail("E_TYPE","conversion numerica requiere entero o float",e.loc);
                            t=parseType(e.text,e.loc);
                            e.resolved="@builtin:cast:"+e.text;
                            break;
                        }
                        if(e.text=="tuple") {
                            if(e.args.size()>16)fail("E_LIMIT","tuple() admite hasta 16 elementos",e.loc);
                            t=Type(Type::Tuple);
                            for(auto& a:e.args){
                                auto et=expr(a,d+1); auto k=et.kind;
                                if(k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::View)
                                    fail("E_PRODUCT_LINEAR","Tuple no admite Borrow/async/View sin prueba de vida",e.loc);
                                t.parts.push_back(et);
                            }
                            requireOwnedTupleVersion(t,fn->module,e.loc);
                            e.resolved="@builtin:tuple.make"; break;
                        }
                        if(e.text=="tuple.get") {
                            if(e.args.size()!=2)fail("E_ARITY","tuple.get requiere tuple e indice literal",e.loc);
                            const bool stable=structuralPlace(e.args[0]);
                            const auto base=stable?provenPlaceType(e.args[0],d+1):expr(e.args[0],d+1);
                            if(!stable&&(typeContainsResource(p,base,fn->module)||containsPending(base)))
                                fail("E_RESOURCE_ACCESS","proyeccion de Tuple temporal owning requiere propietario ligado",e.loc);
                            t=resolveTupleProjection(e,base,d);
                            checkProjectedValueRead(e,t);break;
                        }
                        if(e.text=="array") {
                            if(e.args.empty())fail("E_ARRAY_EMPTY","array() vacio requiere una forma tipada futura",e.loc);
                            if(e.args.size()>65535)fail("E_LIMIT","Array demasiado grande",e.loc);
                            auto et=expr(e.args[0],d+1); auto k=et.kind; if(k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::View)fail("E_PRODUCT_LINEAR","Array no admite Borrow/async/View sin prueba de vida",e.loc);
                            for(size_t i=1;i<e.args.size();++i)need(expr(e.args[i],d+1),et,e.args[i].loc);
                            t=Type(Type::Array); t.parts={et}; t.extent=static_cast<uint32_t>(e.args.size()); e.resolved="@builtin:array.make";
                            requireOwnedTupleVersion(t,fn->module,e.loc); break;
                        }
                        if(e.text=="array.fill") {
                            if(e.args.size()!=2)fail("E_ARITY","array.fill requiere valor y longitud literal",e.loc);
                            auto et=expr(e.args[0],d+1); auto k=et.kind;
                            if(containsPending(et)||typeContainsResource(p,et,fn->module)||k==Type::Resource||k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::Result||k==Type::View)
                                fail("E_PRODUCT_LINEAR","array.fill duplicaria un valor owning/Borrow/async/View",e.loc);
                            auto& n=e.args[1];
                            if(n.kind!=Expr::Number)fail("E_ARRAY_LENGTH","array.fill requiere longitud literal",n.loc);
                            need(expr(n,d+1),Type::U32,n.loc);
                            if(n.value>65535)fail("E_LIMIT","Array demasiado grande",n.loc);
                            t=Type(Type::Array); t.parts={et}; t.extent=static_cast<uint32_t>(n.value);
                            e.binding=static_cast<int>(n.value); e.resolved="@builtin:array.fill"; break;
                        }
                        if(e.text=="array.len") {
                            if(e.args.size()!=1)fail("E_ARITY","array.len requiere Array",e.loc);
                            if(owningArrayPlace(e.args[0])){
                                // the length is static: reading it neither moves nor copies an element
                                const auto base=provenPlaceType(e.args[0],d+1);
                                e.binding=static_cast<int>(base.extent); e.resolved="@builtin:array.len"; t=Type::U32; break;
                            }
                            auto at=expr(e.args[0],d+1);
                            rejectOwningArrayTemporary(at,e.loc);
                            if(at.kind!=Type::Array)fail("E_TYPE","array.len requiere Array",e.loc);
                            e.binding=static_cast<int>(at.extent); e.resolved="@builtin:array.len"; t=Type::U32; break;
                        }
                        if(e.text=="range.exclusive"||e.text=="range.inclusive") {
                            if(e.args.size()!=2)fail("E_ARITY","range requiere inicio y fin",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            t=Type(Type::Range); t.parts={Type::U32};
                            e.resolved=e.text=="range.inclusive"?"@builtin:range.inclusive":"@builtin:range.exclusive";
                            e.binding=e.text=="range.inclusive"?1:0;
                            break;
                        }
                        if(e.text=="index") {
                            if(e.args.size()!=2)fail("E_ARITY","index syntax requiere secuencia e indice",e.loc);
                            if(owningArrayIndex(e,d,t))break;
                            auto st=expr(e.args[0],d+1);
                            rejectOwningArrayTemporary(st,e.loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            if(st.kind==Type::Array){
                                e.binding=static_cast<int>(st.extent); e.resolved="@builtin:array.get"; t=st.parts.at(0); break;
                            }
                            if(st.kind==Type::View){
                                e.resolved="@builtin:view.get"; t=st.parts.at(0); break;
                            }
                            fail("E_INDEX_TYPE","index syntax requiere Array<T,N> o View<T>",e.loc);
                        }
                        if(e.text=="array.get") {
                            if(e.args.size()!=2)fail("E_ARITY","array.get requiere Array e indice",e.loc);
                            if(owningArrayIndex(e,d,t))break;
                            auto at=expr(e.args[0],d+1);
                            rejectOwningArrayTemporary(at,e.loc);
                            if(at.kind!=Type::Array)fail("E_TYPE","array.get requiere Array",e.loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            e.binding=static_cast<int>(at.extent); e.resolved="@builtin:array.get"; t=at.parts.at(0); break;
                        }
                        if(e.text=="array.with") {
                            if(e.args.size()!=3)fail("E_ARITY","array.with requiere Array, indice y valor",e.loc);
                            auto at=expr(e.args[0],d+1);
                            if(at.kind!=Type::Array)fail("E_TYPE","array.with requiere Array",e.loc);
                            if(typeContainsResource(p,at,fn->module)||containsPending(at))fail("E_PRODUCT_LINEAR","array.with descartaria o duplicaria un elemento owning",e.loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            need(expr(e.args[2],d+1),at.parts.at(0),e.args[2].loc);
                            e.binding=static_cast<int>(at.extent); e.resolved="@builtin:array.with"; t=at; break;
                        }
                        if(e.text=="view") {
                            if(e.args.size()!=1)fail("E_ARITY","view requiere una variable Array",e.loc);
                            if(e.args[0].kind!=Expr::Ref)fail("E_VIEW_SOURCE","view requiere una variable Array con lifetime estable",e.loc);
                            const auto sourceBinding=lookup(e.args[0].text,e.args[0].loc);
                            if(sourceBinding.mut)fail("E_VIEW_SOURCE","view requiere una fuente Array inmutable en alpha.5",e.loc);
                            if(sourceBinding.type.kind==Type::Array&&(typeContainsResource(p,sourceBinding.type,fn->module)||containsPending(sourceBinding.type)))
                                fail("E_VIEW_SOURCE","view no admite un Array owning: el prestamo de elementos usa borrow(a[i]) con indice literal",e.loc);
                            auto at=expr(e.args[0],d+1);
                            if(at.kind!=Type::Array)fail("E_VIEW_SOURCE","view requiere Array<T,N>",e.loc);
                            t=Type(Type::View); t.parts={at.parts.at(0)}; e.binding=static_cast<int>(at.extent); e.resolved="@builtin:view.make"; break;
                        }
                        if(e.text=="view.sub") {
                            if(e.args.size()!=3)fail("E_ARITY","view.sub requiere View, offset y length",e.loc);
                            auto vt=expr(e.args[0],d+1); if(vt.kind!=Type::View)fail("E_TYPE","view.sub requiere View<T>",e.loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc); need(expr(e.args[2],d+1),Type::U32,e.args[2].loc);
                            t=vt; e.resolved="@builtin:view.sub"; break;
                        }
                        if(e.text=="view.len") {
                            if(e.args.size()!=1)fail("E_ARITY","view.len requiere View",e.loc);
                            auto vt=expr(e.args[0],d+1); if(vt.kind!=Type::View)fail("E_TYPE","view.len requiere View<T>",e.loc);
                            e.resolved="@builtin:view.len"; t=Type::U32; break;
                        }
                        if(e.text=="view.get") {
                            if(e.args.size()!=2)fail("E_ARITY","view.get requiere View e indice",e.loc);
                            auto vt=expr(e.args[0],d+1); if(vt.kind!=Type::View)fail("E_TYPE","view.get requiere View<T>",e.loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            e.resolved="@builtin:view.get"; t=vt.parts.at(0); break;
                        }
                        if(e.text=="move"&&e.args.size()==1&&expandAggregateMove(e))return expr(e,d);
                        if(e.text=="move"||e.text=="borrow"||e.text=="borrow_mut") {
                            if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere un argumento",e.loc);
                            const auto access=e.text=="move"?ResourceAccessKind::Move:(e.text=="borrow"?ResourceAccessKind::SharedBorrow:ResourceAccessKind::ExclusiveBorrow);
                            t=resourceAccess(e.args[0],access,e.loc);
                            e.binding=e.args[0].placeRoot;
                            e.placeRoot=e.args[0].placeRoot;
                            e.placePath=e.args[0].placePath;
                            e.resolved=e.text=="move"?"@builtin:resource.move":(e.text=="borrow"?"@builtin:resource.borrow":"@builtin:resource.borrow_mut");
                            break;
                        }
                        if(e.text=="bit.and"||e.text=="bit.or"||e.text=="bit.xor"||e.text=="bit.not"||e.text=="bit.shl"||e.text=="bit.shr") {
                            // CP-07 (BIT_INTRINSICS_CANDIDATE.md): declarative integer bit intrinsics, no new syntax.
                            const bool unary=e.text=="bit.not", shift=e.text=="bit.shl"||e.text=="bit.shr";
                            if(e.args.size()!=(unary?1u:2u))fail("E_ARITY",e.text+(unary?" requiere un argumento":" requiere dos argumentos"),e.loc);
                            auto operand=expr(e.args[0],d+1);
                            if(!isInteger(operand))fail("E_TYPE",e.text+" requiere un entero",e.loc);
                            if(shift) {
                                need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                                if(e.args[1].kind==Expr::Number&&e.args[1].value>=integerWidth(operand))
                                    fail("E_BOUNDS","conteo de shift literal fuera del ancho de "+typeName(operand),e.args[1].loc);
                            } else if(!unary) need(expr(e.args[1],d+1),operand,e.args[1].loc);
                            e.resolved="@builtin:"+e.text; t=operand; break;
                        }
                        if(e.text=="bytes.from_text") {
                            if(e.args.size()!=1) fail("E_ARITY","bytes.from_text requiere Text",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.loc);
                            e.resolved="@builtin:bytes.from_text"; t=Type::Bytes; break;
                        }
                        if(e.text=="bytes.len") {
                            if(e.args.size()!=1) fail("E_ARITY","bytes.len requiere Bytes",e.loc);
                            need(expr(e.args[0],d+1),Type::Bytes,e.loc);
                            e.resolved="@builtin:bytes.len"; t=Type::U32; break;
                        }
                        if(e.text=="bytes.concat") {
                            if(e.args.size()!=2) fail("E_ARITY","bytes.concat requiere dos Bytes",e.loc);
                            need(expr(e.args[0],d+1),Type::Bytes,e.loc);
                            need(expr(e.args[1],d+1),Type::Bytes,e.loc);
                            e.resolved="@builtin:bytes.concat"; t=Type::Bytes; break;
                        }
                        if(e.text=="bytes.to_text") {
                            if(e.args.size()!=1) fail("E_ARITY","bytes.to_text requiere Bytes",e.loc);
                            need(expr(e.args[0],d+1),Type::Bytes,e.loc);
                            e.resolved="@builtin:bytes.to_text"; t=Type(Type::Result); t.parts={Type::Text,Type::U32}; break;
                        }
                        // BAREMETAL-001 target primitives. Raw memory, port I/O and privileged CPU
                        // operations are explicit capabilities; none is reachable without them.
                        if(e.text=="raw.load8"||e.text=="raw.load32"||e.text=="raw.load64") {
                            requireCap("memory.raw",e.loc); if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere address u64",e.loc); need(expr(e.args[0],d+1),Type::U64,e.loc);
                            e.resolved="@builtin:"+e.text; t=e.text=="raw.load64"?Type::U64:Type::U32; break;
                        }
                        if(e.text=="raw.store8"||e.text=="raw.store32"||e.text=="raw.store64") {
                            requireCap("memory.raw",e.loc); if(e.args.size()!=2)fail("E_ARITY",e.text+" requiere address u64, value",e.loc); need(expr(e.args[0],d+1),Type::U64,e.loc); need(expr(e.args[1],d+1),e.text=="raw.store64"?Type::U64:Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        // CP-01/CP-04 (OWNED_SLOTS_CANDIDATE.md): slot-bearing buffers whose cells own resources, moved in and out whole (never as integers). The resource
                        // record travels in the call text (`slots.put<mod.Rec>`), as for raw./layout., so Wave, Wire and ONME need no new form.
                        if(e.text.rfind("slots.",0)==0) {
                            std::string base=e.text,recKey;
                            if(const auto lt=e.text.find('<'); lt!=std::string::npos) {
                                if(e.text.back()!='>')fail("E_SLOTS","nombre de llamada de slots invalido: "+e.text,e.loc);
                                base=e.text.substr(0,lt); recKey=slotCallKey(e.text);
                            } else if(e.typeArgs.size()==1) {
                                const Type rt0=resolve(e.typeArgs[0],fn->module,e.loc);
                                if(rt0.kind!=Type::Record)fail("E_GENERIC_CONSTRAINT",e.text+" requiere un struct nominal como argumento de tipo",e.loc);
                                recKey=rt0.key; e.text=base+"<"+recKey+">"; e.typeArgs.clear();
                            }
                            const bool typed=base=="slots.alloc"||base=="slots.state"||base=="slots.gen"||base=="slots.put"||base=="slots.take"||base=="slots.borrow"||base=="slots.borrow_mut";
                            const bool plain=base=="slots.len"||base=="slots.count"||base=="slots.grow"||base=="slots.release";
                            if(!typed&&!plain)fail("E_NAME","primitiva de slots desconocida: "+base,e.loc);
                            if(typed==recKey.empty())fail("E_GENERIC_ARGS",typed?base+" requiere el recurso: "+base+"<Recurso>(...)":base+" no recibe argumento de tipo",e.loc);
                            Type resT(Type::Resource),sharedT(Type::Borrow),mutT(Type::BorrowMut);
                            if(typed) {
                                auto ri=records.find(recKey);
                                if(ri==records.end()||nominalInnerKind(*ri->second)==0)fail("E_RESOURCE_TYPE",base+" requiere un struct nominal de un campo u64 o Resource<Buffer> como recurso",e.loc);
                                if(ri->second->module!=fn->module&&!ri->second->pub&&!generatedTypeAccess(recKey))fail("E_VISIBILITY","struct privado: "+ri->second->name,e.loc);
                                for(Type* q:{&resT,&sharedT,&mutT}){ q->name=recKey; q->key=recKey; }
                            }
                            Type bufRes(Type::Resource),bufMut(Type::BorrowMut); bufRes.name="Buffer"; bufMut.name="Buffer";
                            auto bufferBorrow=[&](const Expr& arg,const Type& got,bool mutableOnly){
                                const bool kindOk=mutableOnly?got.kind==Type::BorrowMut:(got.kind==Type::Borrow||got.kind==Type::BorrowMut);
                                if(!kindOk||got.name!="Buffer")fail("E_TYPE",base+(mutableOnly?" requiere BorrowMut<Buffer>":" requiere Borrow<Buffer> o BorrowMut<Buffer>"),arg.loc);
                            };
                            e.resolved="@builtin:"+base;
                            if(base=="slots.alloc") {
                                requireCap("memory.write",e.loc); if(e.args.size()!=1)fail("E_ARITY","slots.alloc<R> requiere cells",e.loc);
                                need(expr(e.args[0],d+1),Type::U32,e.loc); t=Type(Type::Result); t.parts={bufRes,Type::U32}; break;
                            }
                            if(base=="slots.len"||base=="slots.count") {
                                requireCap("memory.read",e.loc); if(e.args.size()!=1)fail("E_ARITY",base+" requiere Borrow<Buffer> o BorrowMut<Buffer>",e.loc);
                                bufferBorrow(e.args[0],expr(e.args[0],d+1),false); t=Type::U32; break;
                            }
                            if(base=="slots.state"||base=="slots.gen") {   // slots.gen: the generation of a cell (CALLBACK_REGISTRY_HOSTED_CANDIDATE.md)
                                requireCap("memory.read",e.loc); if(e.args.size()!=2)fail("E_ARITY",base+"<R> requiere Borrow<Buffer>, index",e.loc);
                                bufferBorrow(e.args[0],expr(e.args[0],d+1),false); need(expr(e.args[1],d+1),Type::U32,e.loc); t=Type::U32; break;
                            }
                            if(base=="slots.put") {
                                requireCap("memory.write",e.loc); if(e.args.size()!=3)fail("E_ARITY","slots.put<R> requiere BorrowMut<Buffer>, index, move(Resource<R>)",e.loc);
                                need(expr(e.args[0],d+1),bufMut,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); need(expr(e.args[2],d+1),resT,e.loc);
                                t=Type(Type::Result); t.parts={Type::U32,resT}; break;
                            }
                            if(base=="slots.take") {
                                requireCap("memory.write",e.loc); if(e.args.size()!=2)fail("E_ARITY","slots.take<R> requiere BorrowMut<Buffer>, index",e.loc);
                                need(expr(e.args[0],d+1),bufMut,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc);
                                t=Type(Type::Result); t.parts={resT,Type::U32}; break;
                            }
                            if(base=="slots.borrow"||base=="slots.borrow_mut") {
                                const bool mut=base=="slots.borrow_mut";
                                requireCap("memory.read",e.loc); if(e.args.size()!=2)fail("E_ARITY",base+"<R> requiere "+(mut?"BorrowMut":"Borrow")+"<Buffer>, index",e.loc);
                                bufferBorrow(e.args[0],expr(e.args[0],d+1),mut); need(expr(e.args[1],d+1),Type::U32,e.loc);
                                t=mut?mutT:sharedT;
                                // the element stands on the borrow of the buffer it was lent from: growth (BorrowMut) and moves conflict with it while it lives
                                if(e.args[0].kind==Expr::Ref){ const auto pl=loanPlaceForBinding(e.args[0].binding); e.placeRoot=pl.root; e.placePath=pl.projections; }
                                else if(e.args[0].placeRoot>=0){ e.placeRoot=e.args[0].placeRoot; e.placePath=e.args[0].placePath; }
                                else fail("E_PLACE",base+" requiere un Borrow/BorrowMut con Place probado",e.loc);
                                break;
                            }
                            if(base=="slots.grow") {
                                requireCap("memory.write",e.loc); if(e.args.size()!=2)fail("E_ARITY","slots.grow requiere BorrowMut<Buffer>, cells",e.loc);
                                need(expr(e.args[0],d+1),bufMut,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                            }
                            requireCap("memory.write",e.loc); if(e.args.size()!=1)fail("E_ARITY","slots.release requiere move(Resource<Buffer>)",e.loc);   // slots.release
                            need(expr(e.args[0],d+1),bufRes,e.loc); t=Type(Type::Result); t.parts={Type::U32,bufRes}; break;
                        }
                        // CP-11 (TLS_AND_PERCPU_CANDIDATE.md): accesses to the per-thread block (FS-relative) and the per-CPU block (GS-relative).
                        // Each block starts with its size (u64); the offset is checked against it at lowering. Authority: memory.tls / memory.pcpu.
                        // CP-07 (NATIVE_LAYOUT_CANDIDATE.md): layout queries (pure, compile-time) and typed raw memory access over plain records.
                        // The record travels in the call text (`layout.size<mod.Rec>`) so that Wave, Wire and ONME need no new form.
                        if(e.text.rfind("simd.",0)==0) {
                            std::string base=e.text; std::vector<std::string> keys;
                            if(const auto lt=e.text.find('<'); lt!=std::string::npos) {
                                if(e.text.back()!='>')fail("E_SIMD","nombre de llamada simd invalido: "+e.text,e.loc);
                                base=e.text.substr(0,lt); const std::string inner=e.text.substr(lt+1,e.text.size()-lt-2); size_t from=0;
                                for(;;){ const auto c=inner.find(',',from); keys.push_back(inner.substr(from,c==std::string::npos?std::string::npos:c-from)); if(c==std::string::npos)break; from=c+1; }
                            } else {
                                for(const auto& ta:e.typeArgs){ const Type rt0=resolve(ta,fn->module,e.loc); if(rt0.kind!=Type::Record)fail("E_SIMD",e.text+" requiere structs como argumentos de tipo",e.loc); keys.push_back(rt0.key); }
                                if(keys.empty()||keys.size()>2)fail("E_SIMD",e.text+" requiere el tipo del vector (y el de la mascara si compara o selecciona): "+e.text+"<Vector[,Mascara]>",e.loc);
                                e.text=base+"<"+keys[0]+(keys.size()>1?","+keys[1]:std::string())+">"; e.typeArgs.clear();
                            }
                            static const std::set<std::string> twoTypes={"simd.eq","simd.ne","simd.lt","simd.le","simd.gt","simd.ge","simd.select"};
                            static const std::set<std::string> maskOnly={"simd.mask_and","simd.mask_or","simd.mask_xor","simd.mask_not","simd.any","simd.all","simd.bitmask"};
                            static const std::set<std::string> known={"simd.splat","simd.add","simd.sub","simd.mul","simd.div","simd.and","simd.or","simd.xor","simd.reduce_add","simd.load","simd.load_aligned","simd.store","simd.store_aligned"};
                            if(!twoTypes.count(base)&&!maskOnly.count(base)&&!known.count(base))fail("E_SIMD","operacion simd desconocida: "+base,e.loc);
                            if(keys.size()!=(twoTypes.count(base)?2u:1u))fail("E_SIMD",base+(twoTypes.count(base)?" requiere <Vector,Mascara>":" requiere un solo tipo"),e.loc);
                            auto shapeOf=[&](const std::string& k)->VectorShape{
                                auto ri=records.find(k);
                                if(ri==records.end())fail("E_SIMD","struct desconocido: "+k,e.loc);
                                if(ri->second->module!=fn->module&&!ri->second->pub&&!generatedTypeAccess(k))fail("E_VISIBILITY","struct privado: "+ri->second->name,e.loc);
                                auto sh=vectorShape(k); if(!sh.ok)fail("E_SIMD",sh.why,e.loc); return sh;
                            };
                            auto recType=[&](const std::string& k){ Type r(Type::Record); r.name=records.at(k)->name; r.key=k; return r; };
                            const VectorShape A=shapeOf(keys[0]); VectorShape B; if(keys.size()==2)B=shapeOf(keys[1]);
                            const Type V=recType(keys[0]); const Type M=keys.size()==2?recType(keys[1]):V;
                            if(maskOnly.count(base)) { if(!A.mask)fail("E_SIMD",base+" opera sobre una mascara (carriles bool), no sobre "+records.at(keys[0])->name,e.loc); }
                            else if(A.mask)fail("E_SIMD",base+" opera sobre un vector, no sobre la mascara "+records.at(keys[0])->name,e.loc);
                            if(twoTypes.count(base)) { if(!B.mask)fail("E_SIMD",base+": el segundo tipo debe ser una mascara (carriles bool)",e.loc); if(B.lanes!=A.lanes)fail("E_SIMD",base+": el vector y la mascara tienen distinto numero de carriles",e.loc); }
                            auto argc=[&](size_t n){ if(e.args.size()!=n)fail("E_ARITY",base+" requiere "+std::to_string(n)+" argumentos",e.loc); };
                            e.resolved="@builtin:"+base;
                            if(base=="simd.splat") { argc(1); need(expr(e.args[0],d+1),A.lane,e.loc); t=V; break; }
                            if(base=="simd.add"||base=="simd.sub"||base=="simd.mul"||base=="simd.div") {
                                if(base=="simd.div"&&isInteger(A.lane))fail("E_SIMD","simd.div existe solo para carriles f32/f64",e.loc);
                                argc(2); need(expr(e.args[0],d+1),V,e.loc); need(expr(e.args[1],d+1),V,e.loc); t=V; break;
                            }
                            if(base=="simd.and"||base=="simd.or"||base=="simd.xor") {
                                if(!isInteger(A.lane))fail("E_SIMD",base+" existe solo para carriles enteros",e.loc);
                                argc(2); need(expr(e.args[0],d+1),V,e.loc); need(expr(e.args[1],d+1),V,e.loc); t=V; break;
                            }
                            if(twoTypes.count(base)&&base!="simd.select") { argc(2); need(expr(e.args[0],d+1),V,e.loc); need(expr(e.args[1],d+1),V,e.loc); t=M; break; }
                            if(base=="simd.select") { argc(3); need(expr(e.args[0],d+1),M,e.loc); need(expr(e.args[1],d+1),V,e.loc); need(expr(e.args[2],d+1),V,e.loc); t=V; break; }
                            if(base=="simd.mask_and"||base=="simd.mask_or"||base=="simd.mask_xor") { argc(2); need(expr(e.args[0],d+1),V,e.loc); need(expr(e.args[1],d+1),V,e.loc); t=V; break; }
                            if(base=="simd.mask_not") { argc(1); need(expr(e.args[0],d+1),V,e.loc); t=V; break; }
                            if(base=="simd.any"||base=="simd.all") { argc(1); need(expr(e.args[0],d+1),V,e.loc); t=Type::Bool; break; }
                            if(base=="simd.bitmask") { argc(1); need(expr(e.args[0],d+1),V,e.loc); t=Type::U32; break; }
                            if(base=="simd.reduce_add") { argc(1); need(expr(e.args[0],d+1),V,e.loc); t=A.lane; break; }
                            if(base=="simd.load"||base=="simd.load_aligned") { requireCap("memory.raw",e.loc); argc(1); need(expr(e.args[0],d+1),Type::U64,e.loc); t=V; break; }
                            requireCap("memory.raw",e.loc); argc(2); need(expr(e.args[0],d+1),Type::U64,e.loc); need(expr(e.args[1],d+1),V,e.loc); t=Type::U32; break;   // simd.store, simd.store_aligned
                        }
                        if(e.text.rfind("layout.",0)==0||e.text.rfind("raw.read",0)==0||e.text.rfind("raw.write",0)==0) {
                            std::string base=e.text,recKey;
                            if(const auto lt=e.text.find('<'); lt!=std::string::npos) {
                                if(e.text.back()!='>')fail("E_LAYOUT","nombre de llamada de layout invalido: "+e.text,e.loc);
                                base=e.text.substr(0,lt); recKey=e.text.substr(lt+1,e.text.size()-lt-2);
                            } else if(e.typeArgs.size()==1) {
                                const Type rt0=resolve(e.typeArgs[0],fn->module,e.loc);
                                if(rt0.kind!=Type::Record)fail("E_LAYOUT",e.text+" requiere un struct plano como argumento de tipo",e.loc);
                                recKey=rt0.key; e.text=base+"<"+recKey+">"; e.typeArgs.clear();
                            }
                            const bool known=base=="layout.size"||base=="layout.align"||base=="layout.offset"||base=="layout.identity"||base=="raw.read"||base=="raw.write";
                            if(known) {
                                if(recKey.empty())fail("E_LAYOUT",base+" requiere el tipo: "+base+"<Registro>(...)",e.loc);
                                auto ri=records.find(recKey);
                                if(ri==records.end())fail("E_LAYOUT","struct desconocido: "+recKey,e.loc);
                                if(ri->second->module!=fn->module&&!ri->second->pub&&!generatedTypeAccess(recKey))fail("E_VISIBILITY","struct privado: "+ri->second->name,e.loc);
                                if(const auto why=plainRecordProblem(p,recKey); !why.empty())fail("E_LAYOUT",why,e.loc);
                                Type rt(Type::Record); rt.name=ri->second->name; rt.key=recKey;
                                e.resolved="@builtin:"+base;
                                if(base=="layout.size"||base=="layout.align") {
                                    if(!e.args.empty())fail("E_ARITY",base+" no recibe argumentos",e.loc);
                                    t=Type::U64; break;
                                }
                                if(base=="layout.identity") {
                                    if(e.args.size()!=1||e.args[0].kind!=Expr::Number)fail("E_LAYOUT","layout.identity<R> requiere un literal u32 0..3",e.loc);
                                    need(expr(e.args[0],d+1),Type::U32,e.loc);
                                    if(e.args[0].value>3)fail("E_LAYOUT","palabra de identidad fuera de 0..3",e.loc);
                                    e.binding=static_cast<int>(e.args[0].value); t=Type::U64; break;
                                }
                                if(base=="layout.offset") {
                                    if(e.args.size()!=1||e.args[0].kind!=Expr::Ref)fail("E_LAYOUT","layout.offset<R>(campo) requiere el nombre de un campo",e.loc);
                                    int idx=-1; for(size_t i=0;i<ri->second->fields.size();++i)if(ri->second->fields[i].name==e.args[0].text)idx=static_cast<int>(i);
                                    if(idx<0)fail("E_LAYOUT","el struct "+ri->second->name+" no tiene el campo "+e.args[0].text,e.loc);
                                    e.binding=idx; e.args[0].resolved="@field:"+e.args[0].text; t=Type::U64; break;
                                }
                                requireCap("memory.raw",e.loc);
                                if(base=="raw.read") {
                                    if(e.args.size()!=1)fail("E_ARITY","raw.read<R> requiere address u64",e.loc);
                                    need(expr(e.args[0],d+1),Type::U64,e.loc); t=rt; break;
                                }
                                if(e.args.size()!=2)fail("E_ARITY","raw.write<R> requiere address u64 y el valor",e.loc);
                                need(expr(e.args[0],d+1),Type::U64,e.loc); need(expr(e.args[1],d+1),rt,e.loc); t=Type::U32; break;
                            }
                        }
                        if(e.text=="tls.get"||e.text=="tls.set"||e.text=="tls.block_size"||e.text=="tls.init"||e.text=="tls.teardown") {
                            // Typed surface over the block substrate: the variable is named, the compiler owns the offset (THREAD_LOCAL_CANDIDATE.md).
                            requireCap("memory.tls",e.loc);
                            if((e.text=="tls.block_size"||e.text=="tls.init")&&p.threadLocals.empty())fail("E_THREAD_LOCAL",e.text+" requiere al menos una variable thread_local en el programa",e.loc);
                            if(e.text=="tls.block_size"||e.text=="tls.teardown") {
                                if(!e.args.empty())fail("E_ARITY",e.text+" no recibe argumentos",e.loc);
                                e.resolved="@builtin:"+e.text; t=e.text=="tls.block_size"?Type(Type::U64):Type(Type::U32); break;
                            }
                            if(e.text=="tls.init") {
                                requireCap("memory.raw",e.loc);
                                if(e.args.size()!=1)fail("E_ARITY","tls.init requiere base u64",e.loc);
                                need(expr(e.args[0],d+1),Type::U64,e.loc);
                                e.resolved="@builtin:tls.init"; t=Type::U64; break;
                            }
                            const bool setter=e.text=="tls.set";
                            if(e.args.size()!=(setter?2u:1u))fail("E_ARITY",e.text+(setter?" requiere NOMBRE, valor":" requiere NOMBRE"),e.loc);
                            if(e.args[0].kind!=Expr::Ref)fail("E_THREAD_LOCAL",e.text+": el primer argumento debe ser el nombre de una variable thread_local",e.loc);
                            const ThreadLocalDef* def=nullptr;
                            for(const auto& q:p.threadLocals)if(q.module==fn->module&&q.name==e.args[0].text)def=&q;
                            if(!def)fail("E_THREAD_LOCAL","variable thread_local desconocida en este modulo: "+e.args[0].text,e.loc);
                            e.args[0].resolved="@tls:"+def->module+"."+def->name; e.args[0].type=def->type;
                            if(setter)need(expr(e.args[1],d+1),def->type,e.loc);
                            e.resolved="@builtin:"+e.text; t=setter?Type(Type::U32):def->type; break;
                        }
                        if(e.text.rfind("tls.",0)==0||e.text.rfind("pcpu.",0)==0) {
                            const bool tls=e.text[0]=='t'; const std::string op=e.text.substr(tls?4:5);
                            const bool known=op=="load32"||op=="load64"||op=="store32"||op=="store64";
                            if(!known)fail("E_UNDEFINED","operacion de bloque desconocida: "+e.text,e.loc);
                            requireCap(tls?"memory.tls":"memory.pcpu",e.loc);
                            const bool store=op.rfind("store",0)==0, w64=op.compare(op.size()-2,2,"64")==0;
                            if(e.args.size()!=(store?2u:1u))fail("E_ARITY",e.text+(store?" requiere offset u64, value":" requiere offset u64"),e.loc);
                            need(expr(e.args[0],d+1),Type::U64,e.loc);
                            if(store)need(expr(e.args[1],d+1),w64?Type::U64:Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=store?Type::U32:(w64?Type::U64:Type::U32); break;
                        }
                        // ATOMICS-ST09 candidate: atomic cells on u32/u64 with explicit memory orders (literal 0 relaxed,
                        // 1 acquire, 2 release, 3 acq_rel, 4 seq_cst). Authority: memory.atomic (target profile only).
                        if(e.text.rfind("atomic.",0)==0) {
                            const std::string op=e.text.substr(7);
                            const bool w64=op.size()>2&&op.compare(op.size()-2,2,"64")==0, w32=op.size()>2&&op.compare(op.size()-2,2,"32")==0;
                            const std::string base=(w64||w32)?op.substr(0,op.size()-2):op;
                            const Type vt=w64?Type::U64:Type::U32;
                            const bool known=base=="fence"?op=="fence":((base=="load"||base=="store"||base=="cas"||base=="fetch_add")&&(w64||w32));
                            if(!known)fail("E_ATOMIC_OP","operacion atomica desconocida: "+e.text,e.loc);
                            requireCap("memory.atomic",e.loc);
                            const size_t nargs=base=="fence"?1u:(base=="load"?2u:(base=="store"||base=="fetch_add"?3u:5u));
                            if(e.args.size()!=nargs)fail("E_ARITY",e.text+" requiere "+std::to_string(nargs)+" argumentos",e.loc);
                            auto order=[&](size_t i)->uint64_t{
                                if(e.args[i].kind!=Expr::Number||e.args[i].value>4)fail("E_ATOMIC_ORDER",e.text+": el orden debe ser literal 0..4 (relaxed,acquire,release,acq_rel,seq_cst)",e.loc);
                                need(expr(e.args[i],d+1),Type::U32,e.loc); return e.args[i].value;
                            };
                            if(base!="fence")need(expr(e.args[0],d+1),Type::U64,e.loc);
                            if(base=="load") { const auto o=order(1); if(o!=0&&o!=1&&o!=4)fail("E_ATOMIC_ORDER","atomic.load admite relaxed, acquire o seq_cst",e.loc); t=vt; }
                            else if(base=="store") { need(expr(e.args[1],d+1),vt,e.loc); const auto o=order(2); if(o!=0&&o!=2&&o!=4)fail("E_ATOMIC_ORDER","atomic.store admite relaxed, release o seq_cst",e.loc); t=Type::U32; }
                            else if(base=="fetch_add") { need(expr(e.args[1],d+1),vt,e.loc); order(2); t=vt; }
                            else if(base=="cas") {
                                need(expr(e.args[1],d+1),vt,e.loc); need(expr(e.args[2],d+1),vt,e.loc);
                                const auto so=order(3), fo=order(4);
                                if(fo!=0&&fo!=1&&fo!=4)fail("E_ATOMIC_ORDER","el orden de fallo de CAS admite relaxed, acquire o seq_cst",e.loc);
                                const bool okp=so==4||(fo==0)||(fo==1&&(so==1||so==3));
                                if(!okp)fail("E_ATOMIC_ORDER","el orden de fallo de CAS no puede superar al de exito",e.loc);
                                t=vt;
                            }
                            else { const auto o=order(0); if(o==0)fail("E_ATOMIC_ORDER","atomic.fence no admite relaxed",e.loc); t=Type::U32; }
                            e.resolved="@builtin:"+e.text; break;
                        }
                        if(e.text=="port.in8"||e.text=="port.in16"||e.text=="port.in32") {
                            requireCap("port.io",e.loc); if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere port u32",e.loc); need(expr(e.args[0],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="port.out8"||e.text=="port.out16"||e.text=="port.out32") {
                            requireCap("port.io",e.loc); if(e.args.size()!=2)fail("E_ARITY",e.text+" requiere port u32, value u32",e.loc); need(expr(e.args[0],d+1),Type::U32,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.halt") {
                            requireCap("cpu.control",e.loc); if(!e.args.empty())fail("E_ARITY","cpu.halt no admite argumentos",e.loc);
                            e.resolved="@builtin:cpu.halt"; t=Type::U32; break;
                        }
                        if(e.text=="cpu.set_stack"||e.text=="cpu.lgdt"||e.text=="cpu.lidt") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere address u32",e.loc); need(expr(e.args[0],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.write_cr"||e.text=="cpu.read_cr") {
                            const bool w=e.text=="cpu.write_cr"; requireCap("cpu.control",e.loc); if(e.args.size()!=(w?2u:1u))fail("E_ARITY",e.text+(w?" requiere n literal, value u32":" requiere n literal"),e.loc);
                            if(e.args[0].kind!=Expr::Number||(e.args[0].value!=0&&e.args[0].value!=3&&e.args[0].value!=4&&!(!w&&e.args[0].value==2)))fail("E_TARGET_PROFILE",e.text+": n debe ser literal 0, 3 o 4 (lectura: tambien 2)",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.loc); if(w)need(expr(e.args[1],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.sti"||e.text=="cpu.cli"||e.text=="cpu.wait_irq") {
                            requireCap("cpu.control",e.loc); if(!e.args.empty())fail("E_ARITY",e.text+" no admite argumentos",e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.switch_context") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=2)fail("E_ARITY","cpu.switch_context requiere old_area, new_area (u64)",e.loc);
                            for(auto& a:e.args)need(expr(a,d+1),Type::U64,e.loc);
                            e.resolved="@builtin:cpu.switch_context"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.thread_trampoline") {
                            requireCap("cpu.control",e.loc); if(!e.args.empty())fail("E_ARITY","cpu.thread_trampoline no admite argumentos",e.loc);
                            e.resolved="@builtin:cpu.thread_trampoline"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.ltr") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=1)fail("E_ARITY","cpu.ltr requiere selector u32",e.loc); need(expr(e.args[0],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:cpu.ltr"; t=Type::U32; break;
                        }
                        if(e.text=="cpu.enter_ring3"||e.text=="cpu.enter_ring3_interruptible") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=3)fail("E_ARITY",e.text+" requiere entry, user_sp, area (u64)",e.loc);
                            for(auto& a:e.args)need(expr(a,d+1),Type::U64,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U64; break;
                        }
                        if(e.text=="cpu.leave_ring3") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=2)fail("E_ARITY","cpu.leave_ring3 requiere area, value (u64)",e.loc);
                            for(auto& a:e.args)need(expr(a,d+1),Type::U64,e.loc);
                            e.resolved="@builtin:cpu.leave_ring3"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.trap3") {
                            requireCap("cpu.syscall",e.loc); if(e.args.size()!=4)fail("E_ARITY","cpu.trap3 requiere vector literal, nr, a, b (u64)",e.loc);
                            if(e.args[0].kind!=Expr::Number||e.args[0].value<32||e.args[0].value>255)fail("E_TARGET_PROFILE","cpu.trap3: vector debe ser literal 32..255",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.loc); for(size_t i=1;i<4;i++)need(expr(e.args[i],d+1),Type::U64,e.loc);
                            e.resolved="@builtin:cpu.trap3"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.rdtsc") {
                            requireCap("cpu.control",e.loc); if(!e.args.empty())fail("E_ARITY","cpu.rdtsc no admite argumentos",e.loc);
                            e.resolved="@builtin:cpu.rdtsc"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.read_flags") {
                            // CP-14: the guards save the previous interrupt state (RFLAGS.IF) instead of enabling interrupts unconditionally.
                            requireCap("cpu.control",e.loc); if(!e.args.empty())fail("E_ARITY","cpu.read_flags no admite argumentos",e.loc);
                            e.resolved="@builtin:cpu.read_flags"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.read_cr64") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=1)fail("E_ARITY","cpu.read_cr64 requiere n literal",e.loc);
                            if(e.args[0].kind!=Expr::Number||(e.args[0].value!=0&&e.args[0].value!=2&&e.args[0].value!=3&&e.args[0].value!=4))fail("E_TARGET_PROFILE","cpu.read_cr64: n debe ser literal 0, 2, 3 o 4",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:cpu.read_cr64"; t=Type::U64; break;
                        }
                        if(e.text=="cpu.cpuid_sub") {
                            // CP-10 row 10.6 (FPU_SSE_STATE_CANDIDATE.md section 8): CPUID with an explicit sub-leaf (ECX), e.g. leaf 0xD sub-leaf 0/1 for the extended-state area.
                            requireCap("cpu.control",e.loc); if(e.args.size()!=3)fail("E_ARITY","cpu.cpuid_sub requiere hoja u32, subhoja u32, registro literal 0=eax 1=ebx 2=ecx 3=edx",e.loc);
                            if(e.args[2].kind!=Expr::Number||e.args[2].value>3u)fail("E_TARGET_PROFILE","cpu.cpuid_sub: el registro debe ser un literal 0..3",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); need(expr(e.args[2],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:cpu.cpuid_sub"; t=Type::U32; break;
                        }
                        if(e.text=="cpu.rdmsr"||e.text=="cpu.cpuid") {
                            const bool isMsr=e.text=="cpu.rdmsr"; requireCap("cpu.control",e.loc); if(e.args.size()!=2)fail("E_ARITY",e.text+(isMsr?" requiere msr u32, parte literal 0 (bajo) o 1 (alto)":" requiere hoja u32, registro literal 0=eax 1=ebx 2=ecx 3=edx"),e.loc);
                            if(e.args[1].kind!=Expr::Number||e.args[1].value>(isMsr?1u:3u))fail("E_TARGET_PROFILE",e.text+": segundo argumento literal fuera de rango",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.fxsave"||e.text=="cpu.fxrstor") {
                            // CP-10 (FPU_SSE_STATE_CANDIDATE.md): 512-byte, 16-aligned x87/SSE state area; rules are enforced at lowering (trap 12).
                            requireCap("cpu.control",e.loc); if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere area u64",e.loc);
                            need(expr(e.args[0],d+1),Type::U64,e.loc); e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.read_mxcsr"||e.text=="cpu.fninit") {
                            requireCap("cpu.control",e.loc); if(!e.args.empty())fail("E_ARITY",e.text+" no admite argumentos",e.loc);
                            e.resolved="@builtin:"+e.text; t=Type::U32; break;
                        }
                        if(e.text=="cpu.write_mxcsr") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=1)fail("E_ARITY","cpu.write_mxcsr requiere valor u32",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.loc); e.resolved="@builtin:cpu.write_mxcsr"; t=Type::U32; break;
                        }
                        if(e.text=="cpu.call_addr") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=1)fail("E_ARITY","cpu.call_addr requiere address u64",e.loc); need(expr(e.args[0],d+1),Type::U64,e.loc);
                            e.resolved="@builtin:cpu.call_addr"; t=Type::U32; break;
                        }
                        if(e.text=="cpu.wrmsr") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=3)fail("E_ARITY","cpu.wrmsr requiere msr, lo, hi (u32)",e.loc);
                            for(auto& a:e.args)need(expr(a,d+1),Type::U32,e.loc);
                            e.resolved="@builtin:cpu.wrmsr"; t=Type::U32; break;
                        }
                        if(e.text=="cpu.far_jump") {
                            requireCap("cpu.control",e.loc); if(e.args.size()!=2)fail("E_ARITY","cpu.far_jump requiere selector literal, address literal",e.loc);
                            if(e.args[0].kind!=Expr::Number||e.args[1].kind!=Expr::Number)fail("E_TARGET_PROFILE","cpu.far_jump requiere literales (selector, address)",e.loc);
                            for(auto& a:e.args)need(expr(a,d+1),Type::U32,e.loc);
                            e.resolved="@builtin:cpu.far_jump"; t=Type::U32; break;
                        }
                        if(e.text=="buffer.alloc") {
                            requireCap("memory.write",e.loc); if(e.args.size()!=1)fail("E_ARITY","buffer.alloc requiere size",e.loc); need(expr(e.args[0],d+1),Type::U32,e.loc); e.resolved="@builtin:buffer.alloc"; Type rr(Type::Resource); rr.name="Buffer"; t=Type(Type::Result); t.parts={rr,Type::U32}; break;
                        }
                        if(e.text=="buffer.len") {
                            requireCap("memory.read",e.loc); if(e.args.size()!=1)fail("E_ARITY","buffer.len requiere Borrow<Buffer> o BorrowMut<Buffer>",e.loc); auto a=expr(e.args[0],d+1); if((a.kind!=Type::Borrow&&a.kind!=Type::BorrowMut)||a.name!="Buffer")fail("E_TYPE","buffer.len requiere borrow de Buffer",e.loc); e.resolved="@builtin:buffer.len"; t=Type::U32; break;
                        }
                        if(e.text=="buffer.read_u32le"||e.text=="buffer.read_u64le") {
                            const bool wide=e.text=="buffer.read_u64le"; requireCap("memory.read",e.loc); if(e.args.size()!=2)fail("E_ARITY",e.text+" requiere Borrow<Buffer> o BorrowMut<Buffer>, offset",e.loc); auto a0=expr(e.args[0],d+1); if((a0.kind!=Type::Borrow&&a0.kind!=Type::BorrowMut)||a0.name!="Buffer")fail("E_TYPE",e.text+" requiere borrow de Buffer",e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); e.resolved="@builtin:"+e.text; t=Type(Type::Result); t.parts={wide?Type::U64:Type::U32,Type::U32}; break;
                        }
                        if(e.text=="buffer.write_u32le"||e.text=="buffer.write_u64le") {
                            const bool wide=e.text=="buffer.write_u64le"; requireCap("memory.write",e.loc); if(e.args.size()!=3)fail("E_ARITY",e.text+" requiere BorrowMut<Buffer>, offset, value",e.loc); Type br(Type::BorrowMut); br.name="Buffer"; need(expr(e.args[0],d+1),br,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); need(expr(e.args[2],d+1),wide?Type::U64:Type::U32,e.loc); e.resolved="@builtin:"+e.text; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(e.text=="buffer.read_u8") {
                            requireCap("memory.read",e.loc); if(e.args.size()!=2)fail("E_ARITY","buffer.read_u8 requiere Borrow<Buffer> o BorrowMut<Buffer>, index",e.loc); auto a0=expr(e.args[0],d+1); if((a0.kind!=Type::Borrow&&a0.kind!=Type::BorrowMut)||a0.name!="Buffer")fail("E_TYPE","buffer.read_u8 requiere borrow de Buffer",e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); e.resolved="@builtin:buffer.read_u8"; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(e.text=="buffer.write_u8") {
                            requireCap("memory.write",e.loc); if(e.args.size()!=3)fail("E_ARITY","buffer.write_u8 requiere BorrowMut<Buffer>, index, value",e.loc); Type br(Type::BorrowMut); br.name="Buffer"; need(expr(e.args[0],d+1),br,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); need(expr(e.args[2],d+1),Type::U32,e.loc); e.resolved="@builtin:buffer.write_u8"; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(e.text=="buffer.grow") {   // CP-04: growth keeps the same owner; BorrowMut makes every live loan on the buffer a conflict
                            requireCap("memory.write",e.loc); if(e.args.size()!=2)fail("E_ARITY","buffer.grow requiere BorrowMut<Buffer>, new_len",e.loc); Type br(Type::BorrowMut); br.name="Buffer"; need(expr(e.args[0],d+1),br,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); e.resolved="@builtin:buffer.grow"; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(e.text=="buffer.zero") {
                            requireCap("memory.write",e.loc); if(e.args.size()!=3)fail("E_ARITY","buffer.zero requiere BorrowMut<Buffer>, offset, len",e.loc); Type br(Type::BorrowMut); br.name="Buffer"; need(expr(e.args[0],d+1),br,e.loc); need(expr(e.args[1],d+1),Type::U32,e.loc); need(expr(e.args[2],d+1),Type::U32,e.loc); e.resolved="@builtin:buffer.zero"; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(e.text=="buffer.freeze") {
                            requireCap("memory.read",e.loc); if(e.args.size()!=1)fail("E_ARITY","buffer.freeze requiere move(Resource<Buffer>)",e.loc); Type rr(Type::Resource); rr.name="Buffer"; need(expr(e.args[0],d+1),rr,e.loc); e.resolved="@builtin:buffer.freeze"; t=Type(Type::Result); t.parts={Type::Bytes,Type::U32}; break;
                        }
                        if(e.text=="resource.seal"||e.text=="resource.unseal"||e.text=="resource.peek"||e.text=="resource.inner"||e.text=="resource.inner_mut") {
                            if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere un argumento",e.loc);
                            auto a0=expr(e.args[0],d+1);
                            const bool seal=e.text=="resource.seal";
                            std::string rk;
                            if(seal){ if(a0.kind!=Type::Record)fail("E_TYPE","resource.seal requiere un struct nominal",e.loc); rk=a0.key; }
                            else if(e.text=="resource.unseal"){ if(a0.kind!=Type::Resource||!isNominalResource(a0))fail("E_TYPE","resource.unseal requiere move(Resource<R>) nominal",e.loc); rk=a0.name; }
                            else if(e.text=="resource.peek"){ if((a0.kind!=Type::Borrow&&a0.kind!=Type::BorrowMut)||a0.name=="Buffer")fail("E_TYPE","resource.peek requiere Borrow<R>/BorrowMut<R> nominal",e.loc); rk=a0.name; }
                            else {   // resource.inner / resource.inner_mut: the Buffer a nominal resource wraps, as a borrow of the same kind as the argument
                                const bool mut=e.text=="resource.inner_mut";
                                const bool kindOk=mut?a0.kind==Type::BorrowMut:(a0.kind==Type::Borrow||a0.kind==Type::BorrowMut);   // a shared view may come from either borrow
                                if(!kindOk||a0.name=="Buffer")fail("E_TYPE",e.text+(mut?" requiere BorrowMut<R> nominal":" requiere Borrow<R> o BorrowMut<R> nominal"),e.loc);
                                rk=a0.name;
                            }
                            auto ri=records.find(rk);
                            const int inner=ri==records.end()?0:nominalInnerKind(*ri->second);
                            if(inner==0)fail("E_RESOURCE_TYPE","resource.seal/unseal/peek/inner requiere un struct de un campo u64 o Resource<Buffer>",e.loc);
                            if(ri->second->module!=fn->module)fail("E_RESOURCE_PRIVATE",e.text+" solo es valido en el modulo que declara "+rk,e.loc);
                            const bool inward=e.text=="resource.inner"||e.text=="resource.inner_mut";
                            if(inward&&inner!=2)fail("E_RESOURCE_TYPE",e.text+" requiere un recurso nominal que envuelve un Resource<Buffer>",e.loc);
                            if(e.text=="resource.peek"&&inner!=1)fail("E_RESOURCE_TYPE","resource.peek no admite un recurso nominal que posee un Buffer: use resource.inner",e.loc);
                            e.resolved="@builtin:"+e.text+((inner==2&&!inward)?"_buffer":"");
                            if(seal){ Type rr(Type::Resource); rr.name=rk; rr.key=rk; t=rr; }
                            else if(inward){
                                Type bb(e.text=="resource.inner_mut"?Type::BorrowMut:Type::Borrow); bb.name="Buffer"; t=bb;
                                // the Buffer is the same storage as the borrow it came from: the result stands on that borrow's Place, so call-argument conflicts see it
                                if(e.args[0].kind==Expr::Ref){ const auto pl=loanPlaceForBinding(e.args[0].binding); e.placeRoot=pl.root; e.placePath=pl.projections; }
                                else if(e.args[0].placeRoot>=0){ e.placeRoot=e.args[0].placeRoot; e.placePath=e.args[0].placePath; }
                                else fail("E_PLACE",e.text+" requiere un Borrow/BorrowMut con Place probado",e.loc);
                            }
                            else { Type rt(Type::Record); rt.name=ri->second->name; rt.key=rk; t=rt; }
                            break;
                        }
                        if(e.text=="buffer.release" || e.text=="resource.release") {
                            requireCap("memory.write",e.loc); if(e.args.size()!=1)fail("E_ARITY",e.text+" requiere move(Resource<Buffer>)",e.loc); Type rr(Type::Resource); rr.name="Buffer"; need(expr(e.args[0],d+1),rr,e.loc); e.resolved="@builtin:buffer.release"; t=Type::U32; break;
                        }
                        if(e.text=="char.from_u32") {
                            if(e.args.size()!=1)fail("E_ARITY","char.from_u32 requiere u32",e.loc);
                            need(expr(e.args[0],d+1),Type::U32,e.args[0].loc);
                            e.resolved="@builtin:char.from_u32"; t=Type(Type::Result); t.parts={Type::Char,Type::U32}; break;
                        }
                        if(e.text=="char.codepoint") {
                            if(e.args.size()!=1)fail("E_ARITY","char.codepoint requiere Char",e.loc);
                            need(expr(e.args[0],d+1),Type::Char,e.args[0].loc);
                            e.resolved="@builtin:char.codepoint"; t=Type::U32; break;
                        }
                        if(e.text=="text.from_char") {
                            if(e.args.size()!=1)fail("E_ARITY","text.from_char requiere Char",e.loc);
                            need(expr(e.args[0],d+1),Type::Char,e.args[0].loc);
                            e.resolved="@builtin:text.from_char"; t=Type(Type::Result); t.parts={Type::Text,Type::U32}; break;
                        }
                        if(e.text=="text.equals") {
                            if(e.args.size()!=2)fail("E_ARITY","text.equals requiere dos Text",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Text,e.args[1].loc);
                            e.resolved="@builtin:text.equals"; t=Type::Bool; break;
                        }
                        if(e.text=="text.byte_len") {
                            if(e.args.size()!=1)fail("E_ARITY","text.byte_len requiere Text",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            e.resolved="@builtin:text.byte_len"; t=Type::U32; break;
                        }
                        if(e.text=="text.scalar_len") {
                            if(e.args.size()!=1)fail("E_ARITY","text.scalar_len requiere Text",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            e.resolved="@builtin:text.scalar_len"; t=Type::U32; break;
                        }
                        if(e.text=="text.scalar_at") {
                            if(e.args.size()!=2)fail("E_ARITY","text.scalar_at requiere Text e indice u32",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            e.resolved="@builtin:text.scalar_at"; t=Type(Type::Result); t.parts={Type::Char,Type::U32}; break;
                        }
                        if(e.text=="text.len") {
                            if(e.args.size()!=1)fail("E_ARITY","text.len requiere un argumento",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            e.resolved="@builtin:text.len"; t=Type::U32; break;
                        }
                        if(e.text=="text.concat") {
                            if(e.args.size()!=2)fail("E_ARITY","text.concat requiere dos argumentos",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Text,e.args[1].loc);
                            e.resolved="@builtin:text.concat"; t=Type::Text; break;
                        }
                        if(e.text=="host.read") {
                            requireCap("fs.read",e.loc);
                            if(e.args.size()!=2)fail("E_ARITY","host.read requiere ruta Text y max_bytes u32",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::U32,e.args[1].loc);
                            e.resolved="@builtin:host.read"; t=Type(Type::Result); t.parts={Type::Bytes,Type::U32}; break;
                        }
                        if(e.text=="host.write") {
                            requireCap("fs.write",e.loc);
                            if(e.args.size()!=2)fail("E_ARITY","host.write requiere ruta Text y payload Bytes",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Bytes,e.args[1].loc);
                            e.resolved="@builtin:host.write"; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(e.text=="host.process") {
                            requireCap("process.spawn",e.loc);
                            if(e.args.size()!=4)fail("E_ARITY","host.process requiere adapter Text, payload Bytes, max_bytes u32 y deadline_ticks u32",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Bytes,e.args[1].loc);
                            need(expr(e.args[2],d+1),Type::U32,e.args[2].loc);
                            need(expr(e.args[3],d+1),Type::U32,e.args[3].loc);
                            e.resolved="@builtin:host.process"; t=Type(Type::Result); t.parts={Type::Bytes,Type::U32}; break;
                        }
                        if(e.text=="host.tcp") {
                            requireCap("net.connect",e.loc);
                            if(e.args.size()!=4)fail("E_ARITY","host.tcp requiere endpoint Text, payload Bytes, max_bytes u32 y deadline_ticks u32",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Bytes,e.args[1].loc);
                            need(expr(e.args[2],d+1),Type::U32,e.args[2].loc);
                            need(expr(e.args[3],d+1),Type::U32,e.args[3].loc);
                            e.resolved="@builtin:host.tcp"; t=Type(Type::Result); t.parts={Type::Bytes,Type::U32}; break;
                        }
                        if(e.text=="host.ffi") {
                            requireCap("ffi.call",e.loc);
                            if(e.args.size()!=3)fail("E_ARITY","host.ffi requiere library Text, payload Bytes y max_bytes u32",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Bytes,e.args[1].loc);
                            need(expr(e.args[2],d+1),Type::U32,e.args[2].loc);
                            e.resolved="@builtin:host.ffi"; t=Type(Type::Result); t.parts={Type::Bytes,Type::U32}; break;
                        }
                        if(e.text=="file.read_text") {
                            requireCap("fs.read",e.loc);
                            if(e.args.size()!=1)fail("E_ARITY","file.read_text requiere una ruta Text",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            e.resolved="@builtin:file.read_text"; t=Type(Type::Result); t.parts={Type::Text,Type::U32}; break;
                        }
                        if(e.text=="file.write_text") {
                            requireCap("fs.write",e.loc);
                            if(e.args.size()!=2)fail("E_ARITY","file.write_text requiere ruta y Text",e.loc);
                            need(expr(e.args[0],d+1),Type::Text,e.args[0].loc);
                            need(expr(e.args[1],d+1),Type::Text,e.args[1].loc);
                            e.resolved="@builtin:file.write_text"; t=Type(Type::Result); t.parts={Type::U32,Type::U32}; break;
                        }
                        if(auto ev=enumConstructor(e.text,fn->module,e.loc); ev.first) {
                            auto def=ev.first; auto &variant=def->variants.at(static_cast<size_t>(ev.second));
                            if(variant.hasPayload) {
                                if(e.args.size()!=1)fail("E_ARITY","variante "+variant.name+" requiere un payload",e.loc);
                                need(expr(e.args[0],d+1),variant.payload,e.loc);
                            } else if(!e.args.empty()) fail("E_ARITY","variante "+variant.name+" no recibe payload",e.loc);
                            e.kind=Expr::Variant; e.resolved=def->key; e.binding=ev.second; e.indices.clear(); if(variant.hasPayload)e.indices.push_back(variant.payloadField);
                            t=Type(Type::Enum); t.name=def->name; t.key=def->key; break;
                        }
                        e.resolved=e.genericTarget.empty()?key(e.text,fn->module,e.loc,e.generatedReference):e.genericTarget;
                        auto it=funcs.find(e.resolved);
                        if(it==funcs.end())fail("E_CALL","funcion inexistente: "+e.text,e.loc);
                        auto f=it->second;
                        if(f->module!=fn->module&&!f->pub)fail("E_VISIBILITY","funcion privada: "+e.text,e.loc);
                        if(e.args.size()!=f->params.size())fail("E_ARITY","cantidad incorrecta de argumentos: "+e.text,e.loc);
                        fn->calledFunctions.insert(f->key);
                        for(size_t i=0; i<e.args.size(); i++)need(expr(e.args[i],d+1),f->params[i].type,e.args[i].loc);
                        validateLoanArguments(e.args,e.loc);
                        t=f->result;
                        if((t.kind==Type::Borrow||t.kind==Type::BorrowMut)&&borrowReturnAllowedFor!=&e)
                            fail("E_BORROW_ESCAPE","una llamada que devuelve Borrow/BorrowMut debe ser el inicializador directo de un let",e.loc);
                        break;
                    }
                    case Expr::ClosureCall: {
                        if(!e.closureBody)fail("E_CLOSURE","closure sin cuerpo",e.loc);
                        if(collectingClosureCaptures)fail("E_CLOSURE","closures anidadas se difieren fuera de A8.2",e.loc);
                        if(e.closureParams.size()!=e.args.size())fail("E_ARITY","cantidad de argumentos de closure invalida",e.loc);
                        e.annotation=resolve(e.annotation,fn->module,e.loc);
                        if(!closureCaptureAllowed(Binding{e.annotation,false,-1}))
                            fail("E_CLOSURE_CAPTURE","resultado de closure requiere Copy en el alcance inmediato",e.loc);
                        for(auto& a:e.closureParams) {
                            a.type=resolve(a.type,fn->module,a.loc);
                            if(!closureCaptureAllowed(Binding{a.type,false,-1}))
                                fail("E_CLOSURE_CAPTURE","parametro de closure no admitido en A8.2",a.loc);
                        }
                        for(size_t i=0;i<e.args.size();++i)
                            need(expr(e.args[i],d+1),e.closureParams[i].type,e.args[i].loc);
                        const auto outerFn=fn;
                        const auto savedCaptureNames=closureCaptureNames;
                        const auto savedCaptureValues=closureCaptureValues;
                        const auto savedOuterScopeCount=closureOuterScopeCount;
                        const auto savedClosureResultType=closureResultType;
                        collectingClosureCaptures=true;
                        closureResultType=e.annotation;
                        closureOuterScopeCount=scopes.size();
                        closureCaptureNames.clear(); closureCaptureValues.clear();
                        scopes.emplace_back();
                        for(auto& a:e.closureParams)a.binding=declare(a.name,a.type,false,a.loc,true);
                        const bool returns=block(*e.closureBody,d+1);
                        if(!returns)fail("E_CLOSURE_RETURN","no todos los caminos del closure retornan",e.loc);
                        if(!pending.empty())fail("E_RESULT_UNHANDLED","closure deja Result sin tratar",e.loc);
                        scopes.pop_back();
                        e.closureCaptures=closureCaptureNames;
                        e.closureCaptureBindings.clear();
                        for(const auto& b:closureCaptureValues)e.closureCaptureBindings.push_back(b.id);
                        Function generated;
                        generated.name="__closure_"+std::to_string(nextClosure++);
                        generated.module=outerFn->module;
                        generated.key=generated.module+"."+generated.name;
                        generated.result=e.annotation;
                        generated.capabilities=outerFn->capabilities;
                        generated.body=*e.closureBody;
                        generated.locals=outerFn->locals;
                        generated.generated=true;
                        generated.closureGenerated=true;
                        generated.loc=e.loc;
                        for(size_t i=0;i<closureCaptureValues.size();++i)
                            generated.params.push_back({e.closureCaptures[i],closureCaptureValues[i].type,closureCaptureValues[i].id,e.loc,""});
                        generated.params.insert(generated.params.end(),e.closureParams.begin(),e.closureParams.end());
                        generatedClosures.push_back(std::move(generated));
                        e.resolved=generatedClosures.back().key;
                        outerFn->calledFunctions.insert(e.resolved);
                        closureCaptureNames=std::move(savedCaptureNames);
                        closureCaptureValues=std::move(savedCaptureValues);
                        closureOuterScopeCount=savedOuterScopeCount;
                        closureResultType=savedClosureResultType;
                        collectingClosureCaptures=false;
                        t=e.annotation;
                        break;
                    }
                    case Expr::Unary:
                        if(e.args.size()!=1)fail("E_IR","unario invalido",e.loc);
                        if(e.text=="!") {
                            need(expr(e.args[0],d+1),Type::Bool,e.loc);
                            t=Type::Bool;
                            break;
                        }
                        if(e.text=="-") {
                            if(e.args[0].kind==Expr::Number) {
                                auto nt=e.args[0].annotation.kind==Type::Unknown?Type(Type::U32):resolve(e.args[0].annotation,fn->module,e.args[0].loc);
                                if(isFloat(nt)){ e.args[0].type=nt; t=nt; break; }
                                if(!isSignedInteger(nt))fail("E_TYPE","negacion requiere entero signed explicito o float",e.loc);
                                if(!negativeMagnitudeFits(nt,e.args[0].value))fail("E_OVERFLOW_LITERAL","literal negativo fuera de "+typeName(nt),e.loc);
                                e.args[0].type=nt;
                                t=nt;
                                break;
                            }
                            auto a=expr(e.args[0],d+1);
                            if(!isSignedInteger(a)&&!isFloat(a))fail("E_TYPE","negacion requiere entero signed o float",e.loc);
                            t=a;
                            break;
                        }
                        fail("E_IR","unario invalido",e.loc);
                    case Expr::Binary: {
                        if(e.args.size()!=2)fail("E_IR","binario invalido",e.loc);
                        auto a=expr(e.args[0],d+1);
                        auto before=pending;
                        auto b=expr(e.args[1],d+1);
                        need(a,b,e.loc);
                        if(e.text=="&&"||e.text=="||") {
                            if(pending!=before)fail("E_RESULT_FLOW","consumo condicional de Result en cortocircuito",e.loc);
                            need(a,Type::Bool,e.loc);
                            t=Type::Bool;
                        }
                        else if(e.text=="=="||e.text=="!=") {
                            if(!isInteger(a)&&!isFloat(a)&&a.kind!=Type::Bool&&a.kind!=Type::Char)fail("E_TYPE","igualdad agregada no admitida",e.loc);
                            t=Type::Bool;
                        }
                        else {
                            if(a.kind==Type::Char){
                                if(e.text=="<"||e.text=="<="||e.text==">"||e.text==">=")t=Type::Bool;
                                else fail("E_TYPE","Char solo admite igualdad y orden por code point",e.loc);
                                break;
                            }
                            if(!isInteger(a)&&!isFloat(a))fail("E_TYPE","operacion numerica requiere entero o float",e.loc);
                            if(e.text=="<"||e.text=="<="||e.text==">"||e.text==">=")t=Type::Bool;
                            else if(isFloat(a)) {
                                if(e.text=="+"||e.text=="-"||e.text=="*"||e.text=="/")t=a;
                                else fail("E_TYPE","float admite + - * / y comparaciones; wrapping/saturating/% son enteros",e.loc);
                            }
                            else if(e.text=="+"||e.text=="-"||e.text=="*"||e.text=="/"||e.text=="%"||
                                    e.text=="+%"||e.text=="-%"||e.text=="*%"||e.text=="+|"||e.text=="-|"||e.text=="*|")t=a;
                            else fail("E_IR","operacion binaria desconocida",e.loc);
                        }
                        break;
                    }
                    case Expr::RecordInit: {
                        Type raw(Type::Record);
                        raw.name=e.text;
                        t=resolve(raw,fn->module,e.loc);
                        auto def=records.at(t.key);
                        if(def->opaque&&def->module!=fn->module&&!generatedTypeAccess(t.key))fail("E_OPAQUE","struct opaco: su literal sólo se escribe en su módulo ("+def->module+"): "+def->name,e.loc);
                        e.indices.clear();
                        if(e.names.size()!=e.args.size()||e.args.size()!=def->fields.size())fail("E_FIELDS","deben inicializarse todos los campos exactamente una vez",e.loc);
                        std::set<std::string>seen;
                        for(size_t j=0; j<e.args.size(); j++) {
                            if(!seen.insert(e.names[j]).second)fail("E_FIELDS","campo duplicado: "+e.names[j],e.loc);
                            int idx=-1;
                            for(size_t i=0; i<def->fields.size(); i++)if(def->fields[i].name==e.names[j])idx=static_cast<int>(i);
                            if(idx<0)fail("E_FIELDS","campo inexistente: "+e.names[j],e.loc);
                            need(expr(e.args[j],d+1),def->fields[static_cast<size_t>(idx)].type,e.loc);
                            e.indices.push_back(idx);
                        }
                        break;
                    }
                    case Expr::Variant: {
                        auto ev=enumConstructor(e.text,fn->module,e.loc);
                        if(!ev.first && !e.resolved.empty()) {
                            auto it=enums.find(e.resolved);
                            if(it!=enums.end()) { int vi=e.binding; if(vi<0){ for(size_t j=0;j<it->second->variants.size();++j)if(it->second->variants[j].name==e.text)vi=static_cast<int>(j); } ev={it->second,vi}; }
                        }
                        if(!ev.first||ev.second<0||static_cast<size_t>(ev.second)>=ev.first->variants.size())fail("E_IR","constructor enum invalido",e.loc);
                        auto def=ev.first; auto &variant=def->variants.at(static_cast<size_t>(ev.second));
                        if(variant.hasPayload) { if(e.args.size()!=1)fail("E_ARITY","variante requiere payload",e.loc); need(expr(e.args[0],d+1),variant.payload,e.loc); e.indices={variant.payloadField}; }
                        else if(!e.args.empty())fail("E_ARITY","variante no recibe payload",e.loc);
                        e.resolved=def->key; e.binding=ev.second; t=Type(Type::Enum); t.name=def->name; t.key=def->key; break;
                    }
                    case Expr::Field: {
                        if(e.args.size()!=1||!validIdentifier(e.text))fail("E_IR","proyeccion invalida",e.loc);
                        // A resource-bearing record cannot be copied, but its declared
                        // field path remains a valid checker-proven Place. Resolve a
                        // structural Ref/Field base without evaluating it as a value.
                        const bool stable=structuralPlace(e.args[0]);
                        const auto a=stable?provenPlaceType(e.args[0],d+1):expr(e.args[0],d+1);
                        if(!stable&&(typeContainsResource(p,a,fn->module)||containsPending(a)))
                            fail("E_RESOURCE_ACCESS","proyeccion de temporal owning requiere una ley de cleanup probada; ligar el propietario primero",e.loc);
                        t=resolveRecordField(e,a);
                        if(a.kind==Type::Record){ auto ri=records.find(a.key); if(ri!=records.end()&&ri->second->opaque&&ri->second->module!=fn->module&&!generatedTypeAccess(a.key))fail("E_OPAQUE","struct opaco: sus campos sólo se leen en su módulo ("+ri->second->module+"): "+ri->second->name+"."+e.text,e.loc); }
                        checkProjectedValueRead(e,t);
                        break;
                    }
                    case Expr::Ok:case Expr::Err: {
                        if(e.args.size()!=1||e.annotation.kind!=Type::Result)fail("E_IR","constructor Result invalido",e.loc);
                        e.annotation=resolve(e.annotation,fn->module,e.loc);
                        t=e.annotation;
                        need(expr(e.args[0],d+1),t.parts[e.kind==Expr::Ok?0:1],e.loc);
                        break;
                    }
                    case Expr::Some:case Expr::None: {
                        if(e.annotation.kind!=Type::Option)fail("E_IR","constructor Option invalido",e.loc);
                        e.annotation=resolve(e.annotation,fn->module,e.loc);
                        t=e.annotation;
                        if(e.kind==Expr::Some){ if(e.args.size()!=1)fail("E_IR","Some requiere valor",e.loc); need(expr(e.args[0],d+1),t.parts[0],e.loc); }
                        else if(!e.args.empty())fail("E_IR","None no recibe valor",e.loc);
                        break;
                    }
                    default:fail("E_IR","tag de expresion desconocido",e.loc);
                }
                e.type=t;
                return t;
            }
            void requireLoopControlSafe(Loc l) {
                if(loopStack.empty())fail("E_LOOP_CONTROL","break/continue fuera de un bucle",l);
                const auto& snap=loopStack.back();
                if(pending!=snap.pending)fail("E_RESULT_FLOW","break/continue no puede cambiar Results exteriores ni abandonar Result local sin tratar",l);
                for(const auto& kv:snap.ownership){
                    auto it=ownershipLedger.find(kv.first);
                    if(it==ownershipLedger.end()||!(it->second==kv.second))
                        fail("E_RESOURCE_FLOW","break/continue no puede cambiar ownership exterior",l);
                }
                for(const auto& kv:ownershipLedger){
                    if(snap.ownership.count(kv.first))continue;
                    requireNominalDischarged(kv.second,l);
                    if(kv.second.dropRequired&&kv.second.state==OwnershipState::Live)
                        requireAutomaticCleanupVersion(l);
                }
                for(const auto& kv:snap.projected){
                    auto it=projectedOwnership.find(kv.first);
                    if(it==projectedOwnership.end()||it->second!=kv.second)
                        fail("E_RESOURCE_FLOW","break/continue no puede cambiar ownership de campos exterior",l);
                }
                for(const auto& kv:projectedOwnership){
                    if(snap.projected.count(kv.first))continue;
                    requireNominalDischarged(kv.second,l);
                    if(kv.second.dropRequired&&kv.second.state==OwnershipState::Live)
                        requireAutomaticCleanupVersion(l);
                }
            }
            void merge(bool a,const std::set<int>&sa,bool b,const std::set<int>&sb,Loc l) {
                if(a&&b) {
                    pending.clear();
                    return;
                }
                if(a) {
                    pending=sb;
                    return;
                }
                if(b) {
                    pending=sa;
                    return;
                }
                if(sa!=sb)fail("E_RESULT_FLOW","Result debe consumirse de forma consistente en ramas que continuan",l);
                pending=sa;
            }
            void mergeOwnership(bool a,const OwnershipLedger&ra,bool b,const OwnershipLedger&rb,const OwnershipLedger&before,Loc l){
                auto project=[&](const OwnershipLedger&src){
                    OwnershipLedger r;
                    for(const auto&kv:before){
                        auto it=src.find(kv.first);
                        r[kv.first]=it==src.end()?kv.second:it->second;
                    }
                    return r;
                };
                auto pa=project(ra), pb=project(rb);
                if(a&&b){ ownershipLedger=before; return; }
                if(a){ ownershipLedger=pb; return; }
                if(b){ ownershipLedger=pa; return; }
                if(pa!=pb)fail("E_RESOURCE_FLOW","Resource debe moverse/liberarse de forma consistente en ramas que continuan",l);
                ownershipLedger=pa;
            }
            void mergeProjectedOwnership(bool a,const ProjectedOwnership&ra,bool b,const ProjectedOwnership&rb,const ProjectedOwnership&before,Loc l){
                auto project=[&](const ProjectedOwnership&src){
                    ProjectedOwnership r;
                    for(const auto&kv:before){
                        auto it=src.find(kv.first);
                        r[kv.first]=it==src.end()?kv.second:it->second;
                    }
                    return r;
                };
                auto pa=project(ra),pb=project(rb);
                if(a&&b){projectedOwnership=before;return;}
                if(a){projectedOwnership=pb;return;}
                if(b){projectedOwnership=pa;return;}
                if(pa!=pb)fail("E_RESOURCE_FLOW","Resource de campo debe moverse/liberarse de forma consistente en ramas que continuan",l);
                projectedOwnership=pa;
            }
            bool block(std::vector<Stmt>&b,int d,const std::string&arg="",Type argType=Type::Unknown,int*argId=nullptr) {
                if(d>OMNI_LIMIT_BLOCK_DEPTH)fail("E_LIMIT","anidamiento de bloques excesivo");
                scopes.emplace_back();
                if(arg=="_"&&(tracksOwnership(argType)||containsOwnershipLeaves(argType)||isPendingType(argType)))
                    fail("E_RESOURCE_UNCONSUMED","payload owning requiere un binding nombrado para consumo/cleanup",fn->loc);
                if(!arg.empty()&&arg!="_") {
                    int id=declare(arg,argType,false, {
                    });
                    if(argId)*argId=id;
                } else if(arg=="_"&&argId) *argId=-1;
                bool returns=false;
                const size_t currentScopeDepth=scopes.size();
                for(size_t stmtIndex=0;stmtIndex<b.size();++stmtIndex) {
                    auto&s=b[stmtIndex];
                    visit(d,s.loc);
                    if(returns)fail("E_UNREACHABLE","instruccion despues de terminacion garantizada",s.loc);
                    switch(s.kind) {
                        case Stmt::Let:case Stmt::Var: {
                            borrowReturnAllowedFor=(s.kind==Stmt::Let&&s.expr.kind==Expr::Call)?&s.expr:nullptr;
                            auto t=expr(s.expr,1);
                            borrowReturnAllowedFor=nullptr;
                            if(s.declared!=Type::Unknown) {
                                s.declared=resolve(s.declared,fn->module,s.loc);
                                need(t,s.declared,s.loc);
                            }
                            s.binding=declare(s.name,t,s.kind==Stmt::Var,s.loc);
                            if(t.kind==Type::Borrow||t.kind==Type::BorrowMut){
                                const bool direct=s.kind==Stmt::Let&&s.expr.kind==Expr::Call&&
                                    (s.expr.resolved=="@builtin:resource.borrow"||s.expr.resolved=="@builtin:resource.borrow_mut");
                                if(direct){
                                    registerLocalLoan(s.binding,s.expr.binding,Place{s.expr.placeRoot,s.expr.placePath},t.kind==Type::Borrow?LoanKind::Shared:LoanKind::Exclusive,s.name,s.loc);
                                } else {
                                    // CP-02a: let v = f(<region source>) where f returns a Borrow tied to that argument.
                                    auto callee=s.kind==Stmt::Let&&s.expr.kind==Expr::Call?funcs.find(s.expr.resolved):funcs.end();
                                    if(callee==funcs.end())
                                        fail("E_BORROW_ESCAPE","A8.2b local borrow debe originarse directamente en borrow(...) o borrow_mut(...) o en una llamada con region",s.loc);
                                    const Expr* source=nullptr;
                                    for(size_t i=0;i<callee->second->params.size()&&i<s.expr.args.size();++i){
                                        const auto k=callee->second->params[i].type.kind;
                                        if(k==Type::Borrow||k==Type::BorrowMut)source=&s.expr.args[i];
                                    }
                                    if(!source)fail("E_INTERNAL","llamada con region sin argumento fuente",s.loc);
                                    if(source->kind==Expr::Call&&(source->resolved=="@builtin:resource.borrow"||source->resolved=="@builtin:resource.borrow_mut")){
                                        registerLocalLoan(s.binding,source->binding,Place{source->placeRoot,source->placePath},
                                                          source->resolved=="@builtin:resource.borrow"?LoanKind::Shared:LoanKind::Exclusive,s.name,s.loc);
                                    } else if(source->kind==Expr::Ref&&source->binding>=0){
                                        registerLocalLoan(s.binding,source->binding,Place{source->binding,{}},
                                                          source->type.kind==Type::Borrow?LoanKind::Shared:LoanKind::Exclusive,s.name,s.loc);
                                    } else fail("E_BORROW_ESCAPE","el argumento region debe ser borrow(...), borrow_mut(...) o un borrow existente",s.loc);
                                }
                            }
                            break;
                        }
                        case Stmt::Destructure: {
                            auto t=expr(s.expr,1);
                            if(t.kind!=Type::Tuple)fail("E_PATTERN","destructuring requiere Tuple",s.loc);
                            if(t.parts.size()!=s.names.size())fail("E_PATTERN_ARITY","destructuring Tuple tiene aridad incorrecta",s.loc);
                            s.bindings.assign(s.names.size(),-1);
                            std::set<std::string> seen;
                            for(size_t i=0;i<s.names.size();++i){
                                const auto& n=s.names[i];
                                if(n=="_"){
                                    if(t.parts[i].kind==Type::Resource||isPendingType(t.parts[i])||containsOwnershipLeaves(t.parts[i]))
                                        fail("E_RESOURCE_UNCONSUMED","destructuring owning requiere binding nombrado",s.loc);
                                    continue;
                                }
                                if(!seen.insert(n).second)fail("E_PATTERN","binding duplicado en destructuring: "+n,s.loc);
                                s.bindings[i]=declare(n,t.parts[i],false,s.loc);
                            }
                            break;
                        }
                        case Stmt::Assign: {
                            auto v=lookup(s.name,s.loc);
                            if(!v.mut)fail("E_IMMUTABLE","asignacion a valor inmutable: "+s.name,s.loc);
                            need(expr(s.expr,1),v.type,s.loc);
                            s.binding=v.id;
                            break;
                        }
                        case Stmt::Return: {
                        const auto& resultType=collectingClosureCaptures?closureResultType:fn->result;
                        need(expr(s.expr,1),resultType,s.loc);
                        if(resultType.kind==Type::Borrow||resultType.kind==Type::BorrowMut){
                            // CP-02a: only the region-source parameter itself may be returned.
                            int sourceBinding=-1;
                            for(const auto& a:fn->params)if(a.type.kind==Type::Borrow||a.type.kind==Type::BorrowMut)sourceBinding=a.binding;
                            // ... or a projection standing on that parameter's Place (slots.borrow / resource.inner over it), which a local or a temporary never is.
                            const bool isRegion=s.expr.kind==Expr::Ref&&s.expr.binding==sourceBinding;
                            const bool isProjection=s.expr.kind==Expr::Call&&s.expr.placeRoot==sourceBinding&&sourceBinding>=0;   // its type and mode were already matched by need() above
                            if(!isRegion&&!isProjection)
                                fail("E_BORROW_ESCAPE","un Borrow/BorrowMut devuelto debe ser el parametro region o una proyeccion suya, no un local ni un temporal",s.loc);
                        }
                        allHandled(s.loc);
                        allOwnedHandled(s.loc);
                        returns=true;
                        break;
                        }
                        case Stmt::TaskScope: {
                            taskScopes.emplace_back();
                            bool childReturns=block(s.body,d+1);
                            auto unjoined=std::move(taskScopes.back()); taskScopes.pop_back();
                            if(!unjoined.empty())fail("E_TASK_ORPHAN","task_scope termina con Future sin join/cancel",s.loc);
                            returns=childReturns;
                            break;
                        }
                        case Stmt::Spawn: {
                            if(taskScopes.empty())fail("E_TASK_SCOPE","spawn requiere task_scope",s.loc);
                            auto child=expr(s.expr,1);
                            if(!transferable(child))fail("E_TASK_TRANSFER","spawn requiere valor transferible sin borrow/resource/handle",s.loc);
                            Type future(Type::Future); future.parts.push_back(child);
                            s.binding=declare(s.name,future,false,s.loc);
                            taskScopes.back().insert(s.binding);
                            break;
                        }
                        case Stmt::Break:
                        case Stmt::Continue:
                            requireLoopControlSafe(s.loc);
                            returns=true;
                            break;
                        case Stmt::If: {
                            need(expr(s.expr,1),Type::Bool,s.loc);
                            auto before=pending; auto rbefore=ownershipLedger; auto pbefore=projectedOwnership;
                            bool a=block(s.body,d+1);
                            auto pa=pending; auto ra=ownershipLedger; auto pra=projectedOwnership;
                            pending=before; ownershipLedger=rbefore; projectedOwnership=pbefore;
                            bool c=block(s.other,d+1);
                            auto pc=pending; auto rc=ownershipLedger; auto prc=projectedOwnership;
                            merge(a,pa,c,pc,s.loc); mergeOwnership(a,ra,c,rc,rbefore,s.loc); mergeProjectedOwnership(a,pra,c,prc,pbefore,s.loc);
                            returns=a&&c;
                            break;
                        }
                        case Stmt::Loop: {
                            auto beforeCond=pending; auto rbeforeCond=ownershipLedger; auto pbeforeCond=projectedOwnership;
                            need(expr(s.expr,1),Type::Bool,s.loc);
                            if(beforeCond!=pending)fail("E_RESULT_FLOW","condicion repetida no puede consumir Result exterior",s.loc);
                            if(rbeforeCond!=ownershipLedger)fail("E_RESOURCE_FLOW","condicion repetida no puede mover Resource exterior",s.loc);
                            if(pbeforeCond!=projectedOwnership)fail("E_RESOURCE_FLOW","condicion repetida no puede mover Resource de campo exterior",s.loc);
                            auto before=pending; auto rbefore=ownershipLedger; auto pbefore=projectedOwnership;
                            loopStack.push_back({before,rbefore,pbefore});
                            bool r=block(s.body,d+1);
                            loopStack.pop_back();
                            if(!r&&pending!=before)fail("E_RESULT_FLOW","bucle no puede consumir Result exterior repetidamente",s.loc);
                            if(ownershipLedger!=rbefore)fail("E_RESOURCE_FLOW","bucle no puede mover/liberar Resource exterior porque puede ejecutar cero o varias veces",s.loc);
                            if(projectedOwnership!=pbefore)fail("E_RESOURCE_FLOW","bucle no puede mover/liberar Resource de campo exterior porque puede ejecutar cero o varias veces",s.loc);
                            pending=before; ownershipLedger=rbefore; projectedOwnership=pbefore;
                            break;
                        }
                        case Stmt::ForEach: {
                            auto beforeExpr=pending; auto rbeforeExpr=ownershipLedger; auto pbeforeExpr=projectedOwnership;
                            auto seq=expr(s.expr,1);
                            if(seq.kind==Type::Array&&(typeContainsResource(p,seq,fn->module)||containsPending(seq)))
                                fail("E_ITERABLE","for-in no itera un Array owning: cada elemento se consume por indice literal con move(a[i])",s.loc);
                            if(seq.kind==Type::Array)s.iteratorProtocol=Stmt::IteratorArray;
                            else if(seq.kind==Type::View)s.iteratorProtocol=Stmt::IteratorView;
                            else if(seq.kind==Type::Range)s.iteratorProtocol=Stmt::IteratorRange;
                            else fail("E_ITERABLE","for-in requires a resolved static Array<T,N>, View<T> or Range<u32> protocol",s.loc);
                            if(beforeExpr!=pending)fail("E_RESULT_FLOW","for-in iterable expression cannot consume an outer Result",s.loc);
                            if(rbeforeExpr!=ownershipLedger)fail("E_RESOURCE_FLOW","for-in iterable expression cannot move an outer Resource",s.loc);
                            if(pbeforeExpr!=projectedOwnership)fail("E_RESOURCE_FLOW","for-in iterable expression cannot move an outer field Resource",s.loc);
                            auto before=pending; auto rbefore=ownershipLedger; auto pbefore=projectedOwnership;
                            loopStack.push_back({before,rbefore,pbefore});
                            bool r=block(s.body,d+1,s.name,seq.parts.at(0),&s.binding);
                            loopStack.pop_back();
                            if(!r&&pending!=before)fail("E_RESULT_FLOW","for-in body cannot consume outer Result across repeated iterations",s.loc);
                            if(ownershipLedger!=rbefore)fail("E_RESOURCE_FLOW","for-in body cannot move/release outer Resource across repeated iterations",s.loc);
                            if(projectedOwnership!=pbefore)fail("E_RESOURCE_FLOW","for-in body cannot move/release outer field Resource across repeated iterations",s.loc);
                            pending=before; ownershipLedger=rbefore; projectedOwnership=pbefore;
                            break;
                        }
                        case Stmt::Match: {
                            auto t=expr(s.expr,1);
                            if(t.kind!=Type::Result)fail("E_TYPE","match requiere Result",s.loc);
                            auto before=pending; auto rbefore=ownershipLedger; auto pbefore=projectedOwnership;
                            bool a=block(s.body,d+1,s.name,t.parts[0],&s.binding);
                            auto pa=pending; auto ra=ownershipLedger; auto pra=projectedOwnership;
                            pending=before; ownershipLedger=rbefore; projectedOwnership=pbefore;
                            bool c=block(s.other,d+1,s.otherName,t.parts[1],&s.otherBinding);
                            auto pc=pending; auto rc=ownershipLedger; auto prc=projectedOwnership;
                            merge(a,pa,c,pc,s.loc); mergeOwnership(a,ra,c,rc,rbefore,s.loc); mergeProjectedOwnership(a,pra,c,prc,pbefore,s.loc);
                            returns=a&&c;
                            break;
                        }
                        case Stmt::MatchOption: {
                            auto t=expr(s.expr,1);
                            if(t.kind!=Type::Option)fail("E_TYPE","match Some/None requiere Option",s.loc);
                            auto before=pending; auto rbefore=ownershipLedger; auto pbefore=projectedOwnership;
                            bool a=block(s.body,d+1,s.name,t.parts[0],&s.binding);
                            auto pa=pending; auto ra=ownershipLedger; auto pra=projectedOwnership;
                            pending=before; ownershipLedger=rbefore; projectedOwnership=pbefore;
                            bool c=block(s.other,d+1);
                            auto pc=pending; auto rc=ownershipLedger; auto prc=projectedOwnership;
                            merge(a,pa,c,pc,s.loc); mergeOwnership(a,ra,c,rc,rbefore,s.loc); mergeProjectedOwnership(a,pra,c,prc,pbefore,s.loc);
                            returns=a&&c;
                            break;
                        }
                        case Stmt::MatchEnum: {
                            auto t=expr(s.expr,1);
                            if(t.kind!=Type::Enum)fail("E_TYPE","match de variantes requiere enum",s.loc);
                            auto def=enums.at(t.key);
                            if(s.arms.size()!=s.armVariants.size()||s.arms.size()!=s.armNames.size())fail("E_IR","match enum inconsistente",s.loc);
                            std::set<std::string> seen;
                            auto before=pending; auto rbefore=ownershipLedger; auto pbefore=projectedOwnership;
                            std::vector<bool> rs; std::vector<std::set<int>> ps; std::vector<OwnershipLedger> rss; std::vector<ProjectedOwnership> pss;
                            s.armBindings.assign(s.arms.size(),-1); s.armVariantIndices.assign(s.arms.size(),-1); s.armPayloadFields.assign(s.arms.size(),-1);
                            for(size_t ai=0;ai<s.arms.size();++ai){
                                auto &vn=s.armVariants[ai]; if(!seen.insert(vn).second)fail("E_MATCH_DUPLICATE","variante duplicada en match: "+vn,s.loc);
                                int vi=-1; for(size_t j=0;j<def->variants.size();++j)if(def->variants[j].name==vn)vi=static_cast<int>(j);
                                if(vi<0)fail("E_MATCH_VARIANT","variante inexistente en match: "+vn,s.loc);
                                auto &vd=def->variants[static_cast<size_t>(vi)]; s.armVariantIndices[ai]=vi; s.armPayloadFields[ai]=vd.payloadField;
                                if(vd.hasPayload && s.armNames[ai].empty())fail("E_MATCH_BINDING","variante "+vn+" requiere binding de payload",s.loc);
                                if(!vd.hasPayload && !s.armNames[ai].empty())fail("E_MATCH_BINDING","variante "+vn+" no tiene payload",s.loc);
                                pending=before; ownershipLedger=rbefore; projectedOwnership=pbefore;
                                bool rr=vd.hasPayload?block(s.arms[ai],d+1,s.armNames[ai],vd.payload,&s.armBindings[ai]):block(s.arms[ai],d+1);
                                rs.push_back(rr); ps.push_back(pending); rss.push_back(ownershipLedger); pss.push_back(projectedOwnership);
                            }
                            if(seen.size()!=def->variants.size()) { std::string missing; for(auto &vd:def->variants)if(!seen.count(vd.name)){if(!missing.empty())missing+=",";missing+=vd.name;} fail("E_MATCH_NON_EXHAUSTIVE","faltan variantes: "+missing,s.loc); }
                            bool all=true; for(bool x:rs)all=all&&x; returns=all;
                            if(all){ pending.clear(); ownershipLedger=rbefore; projectedOwnership=pbefore; }
                            else {
                                bool have=false; std::set<int> basep; OwnershipLedger baser; ProjectedOwnership baseProjected;
                                for(size_t ai=0;ai<rs.size();++ai)if(!rs[ai]){
                                    if(!have){basep=ps[ai];baser=rss[ai];baseProjected=pss[ai];have=true;}
                                    else { if(basep!=ps[ai])fail("E_RESULT_FLOW","Result debe consumirse consistentemente entre variantes",s.loc);
                                           auto project=[&](const OwnershipLedger&src){OwnershipLedger r; for(auto&kv:rbefore){auto it=src.find(kv.first);r[kv.first]=it==src.end()?kv.second:it->second;}return r;};
                                           if(project(baser)!=project(rss[ai]))fail("E_RESOURCE_FLOW","Resource debe moverse/liberarse consistentemente entre variantes",s.loc);
                                           auto projectFields=[&](const ProjectedOwnership&src){ProjectedOwnership r; for(auto&kv:pbefore){auto it=src.find(kv.first);r[kv.first]=it==src.end()?kv.second:it->second;}return r;};
                                           if(projectFields(baseProjected)!=projectFields(pss[ai]))fail("E_RESOURCE_FLOW","Resource de campo debe moverse/liberarse consistentemente entre variantes",s.loc); }
                                }
                                pending=basep; ownershipLedger=baser; projectedOwnership=baseProjected;
                            }
                            break;
                        }
                        case Stmt::Print: {
                            requireCap("io.print",s.loc);
                            auto t=expr(s.expr,1);
                            if(!isInteger(t)&&!isFloat(t)&&t.kind!=Type::Bool&&t.kind!=Type::Char&&t.kind!=Type::Text)fail("E_TYPE","print requiere numero, bool, Char o Text",s.loc);
                            break;
                        }
                        case Stmt::PrintText: requireCap("io.print",s.loc);
                        if(s.text.size()>4096)fail("E_LIMIT","texto demasiado largo",s.loc);
                        validateUTF8(s.text);
                        for(char raw:s.text){ const auto c=static_cast<unsigned char>(raw); if(c<32&&c!=9&&c!=10&&c!=13)fail("E_STRING","control no admitido",s.loc); }
                        break;
                        default:fail("E_IR","tag de instruccion desconocido",s.loc);
                    }
                    retireDeadLoans(b,stmtIndex+1,currentScopeDepth);
                }
                eraseScopeLoans(currentScopeDepth);
                for(auto&item:scopes.back()){
                    if(pending.count(item.second.id))fail("E_RESULT_UNHANDLED","Result sin tratar al salir de alcance: "+item.first,fn->loc);
                    if(tracksOwnership(item.second.type)){
                        auto it=ownershipLedger.find(item.second.id);
                        if(it==ownershipLedger.end())fail("E_INTERNAL","ownership entry ausente al salir de alcance: "+item.first,fn->loc);
                        if(!returns)requireNominalDischarged(it->second,fn->loc);
                        if(!returns&&it->second.dropRequired&&it->second.state==OwnershipState::Live)
                            requireAutomaticCleanupVersion(fn->loc);
                        // Wave18 lowers this remaining live obligation to deterministic
                        // cleanup.  Moved and explicitly released values never enter the
                        // cleanup plan a second time.
                        ownershipLedger.erase(it);
                    }
                    if(!returns)requireProjectedDischarged(item.second.id,fn->loc);
                    eraseProjectedOwnership(item.second.id);
                }
                scopes.pop_back();
                return returns;
            }
            public: explicit Checker(Program&x):p(x) {
            }
            // CP-10 / MN-04 (spec/SIMD_BASELINE_CANDIDATE.md): a 128-bit vector is a plain record whose 2, 4, 8 or 16 fields are the lanes, all of one integer or float type; a mask is a record of the same
            // number of `bool` lanes. No new type exists: the lanes are the fields, so extract/insert are field read/write and every representation already carries the types.
            struct VectorShape { bool ok=false; bool mask=false; Type lane; size_t lanes=0; std::string why; };
            VectorShape vectorShape(const std::string& key) {
                VectorShape s;
                auto it=records.find(key);
                if(it==records.end()){ s.why="struct desconocido: "+key; return s; }
                const auto& r=*it->second; const size_t n=r.fields.size();
                if(n!=2&&n!=4&&n!=8&&n!=16){ s.why="un vector o una mascara tiene 2, 4, 8 o 16 carriles: "+r.name; return s; }
                const Type lane=r.fields[0].type;
                for(const auto& f:r.fields)if(f.type!=lane){ s.why="todos los carriles de "+r.name+" deben tener el mismo tipo"; return s; }
                s.lane=lane; s.lanes=n;
                if(lane.kind==Type::Bool){ s.mask=true; s.ok=true; return s; }
                const bool integer=isInteger(lane), real=lane.kind==Type::F32||lane.kind==Type::F64;
                if(!integer&&!real){ s.why="los carriles de "+r.name+" deben ser enteros, f32/f64 (vector) o bool (mascara)"; return s; }
                const size_t width=integer?integerWidth(lane):(lane.kind==Type::F32?32:64);
                if(width*n!=128){ s.why=r.name+" no mide 128 bits ("+std::to_string(n)+" carriles de "+std::to_string(width)+" bits)"; return s; }
                s.ok=true; return s;
            }
            std::set<std::string> linkNames;   // export and extern symbols of the program
            static bool linkName(const std::string& s,bool sectionName) {
                if(s.empty()||s.size()>128)return false;
                for(size_t k=0;k<s.size();++k) {
                    const unsigned char c=static_cast<unsigned char>(s[k]);
                    const bool word=std::isalnum(c)||c=='_';
                    if(sectionName) { if(!(word||c=='.'||c=='-'))return false; if(k==0&&c!='.')return false; }
                    else { if(!(word||c=='$'))return false; if(k==0&&std::isdigit(c))return false; }
                }
                return true;
            }
            // MN-07/13/16: what a linkage attribute may say. The C boundary is the SysV integer convention: up to six integer parameters, an integer result.
            void checkLinkage(const Function& f) {
                if(!f.exportName.empty()||f.isExtern) {
                    const std::string& sym=f.isExtern?f.externName:f.exportName;
                    if(!linkName(sym,false))fail("E_LINKAGE","nombre de simbolo invalido: "+sym,f.loc);
                    if(sym.rfind("omni",0)==0||sym.rfind("llvm.",0)==0)fail("E_LINKAGE","el prefijo omni/llvm esta reservado al compilador y su runtime: "+sym,f.loc);
                    if(!linkNames.insert(sym).second)fail("E_LINKAGE","simbolo repetido: "+sym,f.loc);
                    if(f.params.size()>6)fail("E_LINKAGE","un simbolo C admite hasta 6 parametros (registros): "+f.name,f.loc);
                    for(const auto& a:f.params) {
                        if(!isInteger(a.type)||!a.receiverMode.empty())fail("E_LINKAGE","la frontera C solo admite enteros (u8..u64, i8..i64): parametro "+a.name+" de "+f.name+" es "+typeName(a.type),a.loc);
                    }
                    if(!isInteger(f.result))fail("E_LINKAGE","la frontera C solo admite enteros: el resultado de "+f.name+" es "+typeName(f.result),f.loc);
                }
                if(f.isExtern&&!f.capabilities.count("ffi.call"))fail("E_LINKAGE","una funcion extern declara ffi.call: lo que no se ve no se supone puro: "+f.name,f.loc);
                if(!f.section.empty()) {
                    if(!linkName(f.section,true))fail("E_LINKAGE","nombre de seccion invalido: "+f.section,f.loc);
                    if(f.section.rfind(".text.omni_",0)==0)fail("E_LINKAGE","las secciones .text.omni_* son del compilador: "+f.section,f.loc);
                }
            }
            void run() {
                if(!validIdentifier(p.module)||p.modules.empty())fail("E_NAME","modulo de entrada invalido");
                for(auto&m:p.modules) {
                    if(!validIdentifier(m.name)||modules.count(m.name))fail("E_DUPLICATE","modulo duplicado/invalido");
                    modules[m.name]=&m;
                }
                if(!modules.count(p.module))fail("E_MODULE","modulo de entrada ausente");
                for(auto&m:p.modules) {
                    std::set<std::string>names;
                    for(auto&i:m.imports) {
                        if(!validIdentifier(i.alias)||i.alias==m.name||!names.insert(i.alias).second)fail("E_IMPORT","alias duplicado/invalido",i.loc);
                        if(!modules.count(i.target))fail("E_IMPORT","modulo importado ausente: "+i.target,i.loc);
                    }
                }
                std::set<std::string>done,active;
                std::function<void(const std::string&)>dfs=[&](const std::string&n) {
                    if(done.count(n))return;
                    if(!active.insert(n).second)fail("E_IMPORT_CYCLE","ciclo de imports: "+n);
                    for(auto&i:modules.at(n)->imports)dfs(i.target);
                    active.erase(n);
                    done.insert(n);
                };
                dfs(p.module);
                if(done.size()!=modules.size())fail("E_MODULE","bundle contiene modulos no alcanzables");
                {   // CP-11: thread_local declarations (THREAD_LOCAL_CANDIDATE.md)
                    std::set<std::string> seen;
                    for(auto& d:p.threadLocals) {
                        if(!modules.count(d.module)||!validIdentifier(d.name))fail("E_NAME","thread_local invalido",d.loc);
                        if(!seen.insert(d.module+"."+d.name).second)fail("E_DUPLICATE","thread_local duplicado: "+d.name,d.loc);
                        if(!isInteger(d.type))fail("E_THREAD_LOCAL","thread_local admite solo tipos enteros",d.loc);
                        const unsigned bits=integerWidth(d.type);
                        const bool sgn=isSignedInteger(d.type);
                        if(d.negative&&!sgn)fail("E_THREAD_LOCAL","un valor negativo requiere un tipo con signo",d.loc);
                        const uint64_t full=bits==64?UINT64_MAX:((uint64_t(1)<<bits)-1); const uint64_t limit=sgn?(d.negative?(full>>1)+1:(full>>1)):full;
                        if(d.magnitude>limit)fail("E_OVERFLOW_LITERAL","valor inicial fuera del rango de "+typeName(d.type),d.loc);
                        if(d.negative&&d.magnitude==0)fail("E_THREAD_LOCAL","cero negativo no admitido",d.loc);
                    }
                    if(!p.threadLocals.empty())(void)threadLocalLayout(p);   // rejects a block that does not fit
                }
                for(auto&d:p.records) {
                    if(!modules.count(d.module)||!validIdentifier(d.name))fail("E_NAME","struct invalido",d.loc);
                    d.key=d.module+"."+d.name;
                    if(records.count(d.key))fail("E_DUPLICATE","struct duplicado",d.loc);
                    records[d.key]=&d;
                    if(d.fields.empty())fail("E_FIELDS","struct requiere al menos un campo",d.loc);
                }
                for(auto&d:p.enums) {
                    if(!modules.count(d.module)||!validIdentifier(d.name))fail("E_NAME","enum invalido",d.loc);
                    d.key=d.module+"."+d.name;
                    if(records.count(d.key)||enums.count(d.key))fail("E_DUPLICATE","tipo duplicado: "+d.name,d.loc);
                    if(d.variants.empty()||d.variants.size()>OMNI_ENUM_MAX_VARIANTS)fail("E_MATCH","enum requiere 1.."+std::to_string(OMNI_ENUM_MAX_VARIANTS)+" variantes (el tag es de un byte)",d.loc);
                    enums[d.key]=&d;
                }
                for(auto&d:p.enums) {
                    std::set<std::string> names; int payloadField=1;
                    for(auto&v:d.variants){
                        if(!validIdentifier(v.name)||!names.insert(v.name).second)fail("E_DUPLICATE","variante duplicada/invalida: "+v.name,v.loc);
                        if(v.hasPayload){ v.payload=resolve(v.payload,d.module,v.loc); auto k=v.payload.kind; if(k==Type::Borrow||k==Type::BorrowMut||k==Type::Future||k==Type::Stream||k==Type::View)fail("E_TYPE","payload enum async/View/borrow no admitido",v.loc); v.payloadField=payloadField++; if(d.pub)publicType(v.payload,v.loc); }
                    }
                }
                for(auto&d:p.records) {
                    std::set<std::string>names;
                    for(auto&f:d.fields) {
                        if(!validIdentifier(f.name)||!names.insert(f.name).second)fail("E_FIELDS","campo duplicado/invalido",f.loc);
                        f.type=resolve(f.type,d.module,f.loc);
                        // A83 admits owned Resource<Buffer> leaves in immutable
                        // records so proven field Places can exist. Borrows and
                        // Results remain non-aggregate and therefore cannot escape.
                        if(f.type.kind==Type::Borrow||f.type.kind==Type::BorrowMut||f.type.kind==Type::View)fail("E_TYPE","Borrow/View dentro de struct no admitido",f.loc);
                        if(p.representationVersion<18&&f.type.kind==Type::Resource)
                            fail("E_VERSION","Resource de campo requiere Wave18/OMC18",f.loc);
                        if(d.pub)publicType(f.type,f.loc);
                    }
                }
                for(auto&d:p.records) {
                    Type t(Type::Record);
                    t.key=d.key;
                    width(t);
                }
                for(auto&d:p.enums) { Type t(Type::Enum); t.key=d.key; t.name=d.name; width(t); }
                for(auto&f:p.functions) {
                    if(!modules.count(f.module)||!validIdentifier(f.name))fail("E_NAME","funcion invalida",f.loc);
                    f.key=f.module+"."+f.name;
                    if(funcs.count(f.key)||records.count(f.key)||enums.count(f.key))fail("E_DUPLICATE","declaracion duplicada: "+f.name,f.loc);
                    f.requiresOwnedTupleFence=false;
                    signatureFunction=&f; canonicalOk=f.generated;
                    f.result=resolve(f.result,f.module,f.loc);
                    if(f.result.kind==Type::View) fail("E_VIEW_ESCAPE","View<T> cannot be returned from a function in alpha.5",f.loc);
                    if(f.pub&&!canonicalOk)publicType(f.result,f.loc);
                    for(auto&a:f.params) {
                        a.type=resolve(a.type,f.module,a.loc);
                        if(!a.receiverMode.empty()) {
                            if(&a!=&f.params.front())fail("E_METHOD_RECEIVER","receiver debe ser el primer parametro",a.loc);
                            if(a.receiverMode!="read")fail("E_METHOD_RECEIVER","receiver mutate/consume no esta habilitado en A8.2",a.loc);
                            const auto k=a.type.kind;
                            if(tracksOwnership(a.type)||containsPending(a.type)||typeContainsResource(p,a.type,f.module)||k==Type::Borrow||k==Type::BorrowMut||k==Type::View||k==Type::Future||k==Type::Stream||k==Type::Result)
                                fail("E_METHOD_RECEIVER","read receiver requiere un valor Copy sin autoridad",a.loc);
                        }
                        if(f.pub&&!canonicalOk)publicType(a.type,a.loc);
                    }
                    canonicalOk=false; signatureFunction=nullptr;
                    if(f.result.kind==Type::Borrow||f.result.kind==Type::BorrowMut) {
                        // CP-02a: a returned borrow is tied to exactly one borrowed parameter (BORROW_RETURN_REGIONS_CANDIDATE.md).
                        const Param* source=nullptr; size_t sources=0;
                        for(const auto& a:f.params)if(a.type.kind==Type::Borrow||a.type.kind==Type::BorrowMut){ source=&a; ++sources; }
                        if(sources!=1)
                            fail("E_BORROW_ESCAPE","Borrow/BorrowMut devuelto requiere exactamente un parametro Borrow/BorrowMut como region",f.loc);
                        // CP-02 2.4: the result is either the region parameter itself (same mode and type) or a PROJECTION of it - another type, lent for as long as the
                        // parameter is (an element of a container, the buffer inside a resource) - never a mutable view of a shared region. The body proves the derivation
                        // (the return statement below); the caller's loan stays on the argument it passed, so every conflict rule applies to the projection unchanged.
                        const bool sameShape=source->type.kind==f.result.kind&&source->type.name==f.result.name;
                        const bool projection=!sameShape&&(f.result.kind==Type::Borrow||source->type.kind==Type::BorrowMut);
                        if(!sameShape&&!projection)
                            fail("E_BORROW_ESCAPE","el parametro region debe tener el mismo modo y tipo que el Borrow/BorrowMut devuelto, o ser una proyeccion de modo compatible (un BorrowMut solo se proyecta desde un BorrowMut)",f.loc);
                    }
                    if(f.linkage())checkLinkage(f);
                    funcs[f.key]=&f;
                }
                // CP-09: an `extern struct` is a C layout contract: only what C lays out the same way (integers, other plain structs), through the one layout rule the compiler has.
                for(const auto& d:p.records)if(d.externC) {
                    if(const auto why=plainRecordProblem(p,d.key); !why.empty())fail("E_LAYOUT","extern struct "+d.name+": "+why,d.loc);
                }
                for(auto&f:p.functions) {
                    fn=&f;
                    frameSlots=0;
                    f.locals.clear(); f.directCapabilities.clear(); f.requiredCapabilities.clear(); f.excessCapabilities.clear(); f.calledFunctions.clear();
                    scopes.clear();
                    scopes.emplace_back();
                    pending.clear(); ownershipLedger.clear(); projectedOwnership.clear(); loanLedger.clear(); moveSites.clear();
                    for(auto&a:f.params)a.binding=declare(a.name,a.type,false,a.loc,true);
                    // CP-02: a Borrow/BorrowMut parameter is a loan held by the caller for the whole call. Registering it makes `borrow(p)` / `borrow_mut(p)` an ordinary
                    // reborrow (it used to be E_BORROW_EXPIRED because parameters had no ledger entry) and suspends p itself while a child reborrow is live.
                    for(auto&a:f.params)if(a.type.kind==Type::Borrow||a.type.kind==Type::BorrowMut)
                        loanLedger[a.binding]=Loan{a.binding,a.binding,Place{a.binding,{}},a.type.kind==Type::Borrow?LoanKind::Shared:LoanKind::Exclusive,Region{scopes.size()},a.name,true,-1,false,a.loc};
                    if(f.isExtern) { f.directCapabilities=f.capabilities; continue; }   // a declaration: what its callers need is what it declares
                    if(!block(f.body,1))fail("E_RETURN","no todos los caminos retornan: "+f.name,f.loc);
                    // Parameters live in the function-root scope, outside block().
                    // A moved/resource parameter is an ownership transfer into the callee and
                    // must therefore be discharged exactly once before function exit.
                    for(const auto& item:scopes.back()){
                        if(pending.count(item.second.id))
                            fail("E_RESULT_UNHANDLED","Result parametro sin tratar al salir de funcion: "+item.first,f.loc);
                        if(tracksOwnership(item.second.type)){
                            auto it=ownershipLedger.find(item.second.id);
                            if(it==ownershipLedger.end())
                                fail("E_INTERNAL","ownership entry ausente para parametro: "+item.first,f.loc);
                            // Function bodies are required to return on every path. Live owning parameters
                            // were therefore checked on each return edge by allOwnedHandled(); the merged
                            // post-dominator ledger is not an execution path and must not create false leaks.
                            ownershipLedger.erase(it);
                        }
                        eraseProjectedOwnership(item.second.id);
                    }
                }
                // Closure bodies were checked in their lexical context.  Their
                // generated functions deliberately retain those assigned slots,
                // so execution is a plain static call with explicit Copy values.
                if(!generatedClosures.empty()) {
                    budgetCheck("las closures generadas");
                    p.functions.insert(p.functions.end(),std::make_move_iterator(generatedClosures.begin()),std::make_move_iterator(generatedClosures.end()));
                    funcs.clear();
                    for(auto& generated:p.functions)funcs[generated.key]=&generated;
                }
                for(auto&f:p.functions) f.requiredCapabilities=f.directCapabilities;
                bool changed=true; for(size_t round=0; changed && round<p.functions.size()+1; ++round){ changed=false; for(auto&f:p.functions){ auto before=f.requiredCapabilities.size(); for(auto&callee:f.calledFunctions){auto it=funcs.find(callee); if(it!=funcs.end())f.requiredCapabilities.insert(it->second->requiredCapabilities.begin(),it->second->requiredCapabilities.end());} if(f.requiredCapabilities.size()!=before)changed=true; } }
                for(auto&f:p.functions){
                    for(auto&c:f.requiredCapabilities) if(!f.capabilities.count(c)) fail("E_CAPABILITY","funcion "+f.key+" no declara capability transitiva requerida: "+c,f.loc);
                    for(auto&c:f.capabilities) if(!f.requiredCapabilities.count(c)) f.excessCapabilities.insert(c);
                }
            }
        };
        struct Returned {
            Value v;
        };
        struct LoopBreak {};
        struct LoopContinue {};
        class Evaluator  {
            const Program&p;
            const HostPolicy* hostPolicy;
            std::map<std::string,const Function*>funcs;
            uint64_t fuel=1000000;
            uint32_t depth=0;
            std::string output;
            uint64_t nextBuffer=1;
            size_t bufferBytes=0;
            std::map<uint64_t,std::vector<uint8_t>> buffers;
            // CP-03 (spec/CLEANUP_FAILURE_CANDIDATE.md): the same acquisition fail point and the same audit stream as the C runtime. OMNI_FAIL_AT=N fails the N-th
            // acquisition (buffer alloc/grow, slots alloc/grow) with outcome 3; OMNI_RESOURCE_AUDIT=1 prints "audit acq|rel <n>" and a summary when the run ends.
            uint64_t failAt=0, failSeen=0;
            uint32_t genMax=UINT32_MAX;   // OMNI_SLOT_GEN_MAX lowers the generation horizon of the slots (CALLBACK_REGISTRY_HOSTED_CANDIDATE.md)
            bool auditOn=false;
            uint32_t auditAcq=0, auditRel=0;
            std::map<uint64_t,uint32_t> auditId;
            bool acquisitionFails() { return failAt!=0&&++failSeen==failAt; }
            void auditAcquire(uint64_t h) { auditId[h]=++auditAcq; if(auditOn)std::fprintf(stderr,"audit acq %u\n",auditAcq); }
            void auditRelease(uint64_t h) { ++auditRel; auto i=auditId.find(h); if(auditOn&&i!=auditId.end())std::fprintf(stderr,"audit rel %u\n",i->second); }
            // A handle never issued is E_RESOURCE_HANDLE; one that was issued and released is a double release (when releasing) or a use after release.
            [[noreturn]] void badBuffer(uint64_t h,bool releasing) {
                if(h==0||h>=nextBuffer)fail("E_RESOURCE_HANDLE","Buffer invalido");
                fail(releasing?"E_RESOURCE_DOUBLE_RELEASE":"E_RESOURCE_STALE_USE",releasing?"Buffer ya liberado":"uso de un Buffer ya liberado");
            }
            // CP-01/CP-04: the buffers that own resources in cells of 8 bytes (spec/OWNED_SLOTS_CANDIDATE.md); the evaluator mirrors the runtime exactly.
            struct SlotMeta { std::string tag; std::vector<uint8_t> occ; std::vector<uint32_t> gen; };
            std::map<uint64_t,SlotMeta> slotMeta;
            static size_t slotsOccupied(const SlotMeta& m) { size_t c=0; for(auto b:m.occ)c+=b!=0; return c; }
            // Freeing a slot-bearing buffer that still owns resources would lose them silently: it is a fault (slots.release refuses instead).
            void dropSlotBuffer(uint64_t h) {
                auto m=slotMeta.find(h); if(m==slotMeta.end())return;
                if(slotsOccupied(m->second)!=0)fail("E_SLOT_OCCUPIED","un buffer de slots que aun posee recursos no se libera: use slots.take y consuma cada uno");
                bufferBytes-=m->second.occ.size()*5u; slotMeta.erase(m);
            }
            std::map<uint64_t,uint8_t> rawMemory;
            std::vector<uint64_t> portLog;
            struct ChannelState { Type element; uint32_t capacity=0; bool closed=false; std::deque<Value> queue; };
            uint64_t nextChannel=1;
            std::map<uint64_t,ChannelState> channels;
            void cleanupValue(Value& value) {
                if(value.type.kind==Type::Resource) {
                    // A zero handle is the runtime moved/dropped sentinel.  The
                    // checker is still responsible for rejecting a source-level
                    // double move/release; this guard prevents generated cleanup
                    // from replaying an already discharged obligation.
                    if(!value.handle)return;
                    if(value.type.name!="Buffer")return;   // nominal handle: proven consumed by the checker (no automatic cleanup)
                    auto it=buffers.find(value.handle);
                    if(it==buffers.end())fail("E_INTERNAL","cleanup plan reached an invalid Resource handle");
                    dropSlotBuffer(value.handle);
                    bufferBytes-=it->second.size();
                    auditRelease(value.handle);
                    buffers.erase(it);
                    value.handle=0;
                    return;
                }
                // Only nominal records own projected Resource leaves.  Result
                // payloads are consumed by match and are not an additional
                // owner after their selected payload binding is introduced.
                if(value.type.kind==Type::Array){
                    const auto elementKind=value.type.parts.at(0).kind;
                    if(isInteger(value.type.parts.at(0))||isFloat(value.type.parts.at(0))||elementKind==Type::Bool||elementKind==Type::Char||
                       elementKind==Type::Text||elementKind==Type::Bytes||!typeContainsResource(p,value.type,p.module))return;   // plain arrays own nothing
                }
                if(value.type.kind==Type::Record||value.type.kind==Type::Tuple||value.type.kind==Type::Array)
                    for(auto it=value.fields.rbegin();it!=value.fields.rend();++it)cleanupValue(*it);
            }
            void cleanupBindings(std::vector<Value>& env,const std::vector<int>& bindings) {
                for(auto it=bindings.rbegin();it!=bindings.rend();++it)
                    if(*it>=0)cleanupValue(env.at(static_cast<size_t>(*it)));
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
            void consumePlace(const Expr& e,std::vector<Value>& env) {
                if(e.placeRoot<0)fail("E_INTERNAL","move without a checked Place");
                Value* slot=&env.at(static_cast<size_t>(e.placeRoot));
                for(const auto field:e.placePath) {
                    if(field<0||static_cast<size_t>(field)>=slot->fields.size())
                        fail("E_INTERNAL","move Place does not resolve at runtime");
                    slot=&slot->fields.at(static_cast<size_t>(field));
                }
                if(slot->type.kind!=Type::Resource)fail("E_INTERNAL","move Place is not a Resource at runtime");
                slot->handle=0;
            }
            void tick() {
                if(!fuel)fail("E_FUEL","limite de pasos agotado");
                --fuel;
            }
            Value call(const std::string&name,const std::vector<Value>&args) {
                if(++depth>128)fail("E_DEPTH","limite de llamadas agotado");
                auto f=funcs.at(name);
                if(f->isExtern)fail("E_TARGET_PROFILE","una funcion extern no es ejecutable en el evaluador: "+f->externName);
                if(args.size()!=f->params.size())fail("E_ARITY","argumentos de evaluacion invalidos");
                std::vector<Value>env(f->locals.size());
                for(size_t i=0; i<args.size(); i++) {
                    if(args[i].type!=f->params[i].type)fail("E_TYPE","argumento incompatible");
                    env[static_cast<size_t>(f->params[i].binding)]=args[i];
                }
                try {
                    block(f->body,env);
                }
                catch(const Returned&r) {
                    std::vector<int> parameters;
                    for(const auto& parameter:f->params)parameters.push_back(parameter.binding);
                    cleanupBindings(env,parameters);
                    --depth;
                    return r.v;
                }
                catch(...) {
                    std::vector<int> parameters;
                    for(const auto& parameter:f->params)parameters.push_back(parameter.binding);
                    cleanupBindings(env,parameters);
                    --depth;
                    throw;
                }
                fail("E_INTERNAL","funcion sin retorno validado");
            }
            Value expr(const Expr&e,std::vector<Value>&env) {
                tick();
                switch(e.kind) {
                    case Expr::Number:return Value(e.type,isFloat(e.type)?e.value:(e.value&intMask(e.type)));
                    case Expr::Boolean:return Value(Type::Bool,e.value);
                    case Expr::Text:return Value(Type::Text,e.text);
                    case Expr::Ref:return env.at(static_cast<size_t>(e.binding));
                    case Expr::Call: {
                        // Never evaluate the name argument of tls.get/tls.set/layout.offset as an expression.
                        if(e.resolved.rfind("@builtin:tls.",0)==0||e.resolved.rfind("@builtin:pcpu.",0)==0)
                            fail("E_TARGET_PROFILE","los bloques por hilo/por CPU dependen de FS/GS y no son ejecutables en el evaluador: "+e.text);
                        if(e.resolved=="@builtin:layout.identity") {
                            const auto lt=e.text.find('<'); const auto key=e.text.substr(lt+1,e.text.size()-lt-2);
                            return Value(Type::U64,recordIdentityWord(p,key,static_cast<unsigned>(e.binding)));
                        }
                        if(e.resolved=="@builtin:layout.size"||e.resolved=="@builtin:layout.align"||e.resolved=="@builtin:layout.offset") {
                            // pure and compile-time: the evaluator answers with the x86-64 rules (the freestanding i386 profile caps alignment at 4)
                            const auto lt=e.text.find('<'); const auto key=e.text.substr(lt+1,e.text.size()-lt-2);
                            const auto layout=recordLayout(p,key,8);
                            if(e.resolved=="@builtin:layout.size")return Value(Type::U64,layout.size);
                            if(e.resolved=="@builtin:layout.align")return Value(Type::U64,layout.align);
                            return Value(Type::U64,layout.offsets.at(static_cast<size_t>(e.binding)));
                        }
                        std::vector<Value>a;
                        for(auto&v:e.args)a.push_back(expr(v,env));
                        if(e.resolved.rfind("@builtin:cast:",0)==0) return Value(e.type,numericCastBits(a[0].type,e.type,a[0].bits));
                        if(e.resolved.rfind("@builtin:simd.",0)==0) return simd(e,a);
                        if(e.resolved=="@builtin:range.exclusive"||e.resolved=="@builtin:range.inclusive") {
                            Value v(e.type,e.resolved=="@builtin:range.inclusive"?1u:0u);
                            v.fields={Value(Type::U32,a[0].bits),Value(Type::U32,a[1].bits)};
                            return v;
                        }
                        if(e.resolved=="@builtin:tuple.make"||e.resolved=="@builtin:array.make") { Value v(e.type); v.fields=std::move(a); return v; }
                        if(e.resolved=="@builtin:tuple.get"||e.resolved=="@builtin:array.place") return a[0].fields.at(static_cast<size_t>(e.binding));
                        if(e.resolved=="@builtin:array.fill") { Value v(e.type); v.fields.assign(static_cast<size_t>(e.binding),a[0]); return v; }
                        if(e.resolved=="@builtin:array.len") return Value(Type::U32,static_cast<uint64_t>(e.binding));
                        if(e.resolved=="@builtin:array.get") { auto i=a[1].bits; if(i>=a[0].fields.size())fail("E_BOUNDS","indice Array fuera de rango"); return a[0].fields.at(static_cast<size_t>(i)); }
                        if(e.resolved=="@builtin:array.with") { auto i=a[1].bits; if(i>=a[0].fields.size())fail("E_BOUNDS","indice Array fuera de rango"); Value v=a[0]; v.fields.at(static_cast<size_t>(i))=a[2]; return v; }
                        if(e.resolved=="@builtin:view.make") { Value v(e.type); v.fields=a[0].fields; return v; }
                        if(e.resolved=="@builtin:view.sub") { auto off=a[1].bits, len=a[2].bits; if(off>a[0].fields.size()||len>a[0].fields.size()-static_cast<size_t>(off))fail("E_BOUNDS","rango View fuera de limites"); Value v(e.type); auto first=a[0].fields.begin()+static_cast<std::ptrdiff_t>(off); auto last=first+static_cast<std::ptrdiff_t>(len); v.fields.assign(first,last); return v; }
                        if(e.resolved=="@builtin:view.len") return Value(Type::U32,static_cast<uint32_t>(a[0].fields.size()));
                        if(e.resolved=="@builtin:view.get") { auto i=a[1].bits; if(i>=a[0].fields.size())fail("E_BOUNDS","indice View fuera de rango"); return a[0].fields.at(static_cast<size_t>(i)); }
                        if(e.resolved=="@builtin:resource.move") { auto moved=a[0]; consumePlace(e,env); return moved; }
                        if(e.resolved=="@builtin:resource.seal") { Value v(e.type); v.handle=a[0].fields.at(0).bits; return v; }
                        if(e.resolved=="@builtin:resource.seal_buffer") { Value v(e.type); v.handle=a[0].fields.at(0).handle; return v; }
                        if(e.resolved=="@builtin:resource.unseal_buffer") { Type bt(Type::Resource); bt.name="Buffer"; Value inner(bt); inner.handle=a[0].handle; Value v(e.type); v.fields={inner}; return v; }
                        if(e.resolved=="@builtin:resource.inner"||e.resolved=="@builtin:resource.inner_mut") { Value v(e.type); v.handle=a[0].handle; return v; }
                        if(e.resolved=="@builtin:resource.unseal"||e.resolved=="@builtin:resource.peek") { Value v(e.type); v.fields={Value(Type::U64,a[0].handle)}; return v; }
                        if(e.resolved=="@builtin:resource.borrow"||e.resolved=="@builtin:resource.borrow_mut") { Value v(e.type); v.handle=a[0].handle; return v; }
                        if(e.resolved=="@builtin:bytes.from_text") return Value(Type::Bytes,a[0].text);
                        if(e.resolved.rfind("@builtin:bit.",0)==0) {
                            const auto op=e.resolved.substr(13); const auto& ty=e.args[0].type;
                            const uint64_t mask=intMask(ty), x=a[0].bits&mask; uint64_t r=0;
                            if(op=="and")r=x&(a[1].bits&mask);
                            else if(op=="or")r=x|(a[1].bits&mask);
                            else if(op=="xor")r=x^(a[1].bits&mask);
                            else if(op=="not")r=~x&mask;
                            else {
                                const uint64_t count=a[1].bits&0xffffffffu;
                                if(count>=integerWidth(ty))fail("E_BOUNDS","conteo de shift fuera del ancho de "+typeName(ty));
                                if(op=="shl")r=(x<<count)&mask;
                                else r=isSignedInteger(ty)?encodeSigned(ty,signedBits(ty,x)>>count):(x>>count);
                            }
                            return Value(e.type,r);
                        }
                        if(e.resolved=="@builtin:bytes.len") return Value(Type::U32,static_cast<uint32_t>(a[0].text.size()));
                        if(e.resolved=="@builtin:bytes.concat") { if(a[0].text.size()+a[1].text.size()>OMNI_TEXT_VALUE_LIMIT_BYTES)fail("E_BYTES_LIMIT","Bytes concat excede 1 MiB"); return Value(Type::Bytes,a[0].text+a[1].text); }
                        if(e.resolved=="@builtin:bytes.to_text") { Value r(e.type,0); try{ validateUTF8(a[0].text); r.bits=1; r.fields.push_back(Value(Type::Text,a[0].text)); } catch(const Error&){ r.fields.push_back(Value(Type::U32,1)); } return r; }
                        if(e.resolved=="@builtin:buffer.alloc") {
                            Value r(e.type,0); auto n=a[0].bits; if(acquisitionFails()){r.fields.push_back(Value(Type::U32,3));return r;} if(n>1024u*1024u){r.fields.push_back(Value(Type::U32,1));return r;} if(buffers.size()>=1024||bufferBytes+n>16u*1024u*1024u){r.fields.push_back(Value(Type::U32,2));return r;}
                            try{ buffers[nextBuffer]=std::vector<uint8_t>(n); }catch(...){r.fields.push_back(Value(Type::U32,3));return r;} bufferBytes+=n; Type rt(Type::Resource);rt.name="Buffer"; Value v(rt);v.handle=nextBuffer++; auditAcquire(v.handle); r.bits=1;r.fields.push_back(v);return r;
                        }
                        // BAREMETAL-001: the evaluator models raw memory as a sparse byte map (zero-filled);
                        // port reads return 0xFF, port writes are recorded; CPU control is not executable here.
                        if(e.resolved=="@builtin:raw.load8"||e.resolved=="@builtin:raw.load32"||e.resolved=="@builtin:raw.load64") {
                            const size_t w=e.resolved=="@builtin:raw.load8"?1:(e.resolved=="@builtin:raw.load32"?4:8); uint64_t v=0;
                            for(size_t k=0;k<w;++k){ auto it=rawMemory.find(a[0].bits+k); if(it!=rawMemory.end())v|=static_cast<uint64_t>(it->second)<<(8*k); }
                            return Value(w==8?Type::U64:Type::U32,v);
                        }
                        if(e.resolved=="@builtin:raw.store8"||e.resolved=="@builtin:raw.store32"||e.resolved=="@builtin:raw.store64") {
                            const size_t w=e.resolved=="@builtin:raw.store8"?1:(e.resolved=="@builtin:raw.store32"?4:8);
                            if(w==1&&a[1].bits>255)fail("E_CAST_RANGE","raw.store8 requiere value <= 255");
                            for(size_t k=0;k<w;++k)rawMemory[a[0].bits+k]=static_cast<uint8_t>((a[1].bits>>(8*k))&255u);
                            return Value(Type::U32,0);
                        }
                        if(e.resolved=="@builtin:raw.read"||e.resolved=="@builtin:raw.write") {
                            // CP-07: the same field-by-field access as the native lowering, over the evaluator's sparse memory (x86-64 alignment rules).
                            const auto lt=e.text.find('<'); const auto key=e.text.substr(lt+1,e.text.size()-lt-2);
                            const auto lay=recordLayout(p,key,8);
                            if(a[0].bits==0||(lay.align>1&&(a[0].bits&(lay.align-1))!=0))fail("E_LAYOUT","acceso a struct nulo o desalineado en el evaluador: "+e.text);
                            auto find=[&](const std::string& k)->const RecordDef& { for(const auto& r:p.records)if(r.key==k)return r; fail("E_INTERNAL","struct sin definicion: "+k); };
                            std::function<Value(const std::string&,uint64_t)> readRecord=[&](const std::string& k,uint64_t at)->Value {
                                const auto& rec=find(k); const auto rl=recordLayout(p,k,8);
                                Type rt(Type::Record); rt.name=rec.name; rt.key=k; Value v(rt);
                                for(size_t i=0;i<rec.fields.size();++i) {
                                    const auto fa=at+rl.offsets[i];
                                    if(isInteger(rec.fields[i].type)) {
                                        uint64_t bits=0; const size_t w=integerWidth(rec.fields[i].type)/8;
                                        for(size_t b=0;b<w;++b){ auto it=rawMemory.find(fa+b); if(it!=rawMemory.end())bits|=static_cast<uint64_t>(it->second)<<(8*b); }
                                        v.fields.push_back(Value(rec.fields[i].type,bits));
                                    } else v.fields.push_back(readRecord(rec.fields[i].type.key,fa));
                                }
                                return v;
                            };
                            std::function<void(const std::string&,uint64_t,const Value&)> writeRecord=[&](const std::string& k,uint64_t at,const Value& value) {
                                const auto& rec=find(k); const auto rl=recordLayout(p,k,8);
                                for(const auto& gap:rl.padding)for(uint64_t b=0;b<gap.second;++b)rawMemory[at+gap.first+b]=0;
                                for(size_t i=0;i<rec.fields.size();++i) {
                                    const auto fa=at+rl.offsets[i];
                                    if(isInteger(rec.fields[i].type)) {
                                        const size_t w=integerWidth(rec.fields[i].type)/8;
                                        for(size_t b=0;b<w;++b)rawMemory[fa+b]=static_cast<uint8_t>((value.fields.at(i).bits>>(8*b))&255u);
                                    } else writeRecord(rec.fields[i].type.key,fa,value.fields.at(i));
                                }
                            };
                            if(e.resolved=="@builtin:raw.read")return readRecord(key,a[0].bits);
                            writeRecord(key,a[0].bits,a[1]);
                            return Value(Type::U32,0);
                        }
                        if(e.resolved.rfind("@builtin:atomic.",0)==0) {
                            // single-flow model over the same sparse memory as raw.*: it checks alignment and values,
                            // it proves NO inter-CPU ordering (the evaluator has one thread).
                            const std::string op=e.resolved.substr(16);
                            if(op=="fence") return Value(Type::U32,0);
                            const bool w64=op.compare(op.size()-2,2,"64")==0; const size_t w=w64?8:4; const uint64_t mask=w64?~0ull:0xffffffffull;
                            const uint64_t ad=a[0].bits; if(ad==0||ad%w!=0)fail("E_ATOMIC_ALIGN","acceso atomico sin alineacion natural o nulo");
                            auto rd=[&]{ uint64_t v=0; for(size_t k=0;k<w;++k){ auto it=rawMemory.find(ad+k); if(it!=rawMemory.end())v|=static_cast<uint64_t>(it->second)<<(8*k); } return v; };
                            auto wr=[&](uint64_t v){ for(size_t k=0;k<w;++k)rawMemory[ad+k]=static_cast<uint8_t>((v>>(8*k))&255u); };
                            const auto rt=w64?Type::U64:Type::U32;
                            if(op.rfind("load",0)==0) return Value(rt,rd());
                            if(op.rfind("store",0)==0) { wr(a[1].bits&mask); return Value(Type::U32,0); }
                            if(op.rfind("fetch_add",0)==0) { const uint64_t old=rd(); wr((old+a[1].bits)&mask); return Value(rt,old); }
                            const uint64_t old=rd(); if(old==(a[1].bits&mask))wr(a[2].bits&mask); return Value(rt,old);
                        }
                        if(e.resolved=="@builtin:port.in8") return Value(Type::U32,255);
                        if(e.resolved=="@builtin:port.in16") return Value(Type::U32,65535);
                        if(e.resolved=="@builtin:port.in32") return Value(Type::U32,4294967295u);
                        if(e.resolved=="@builtin:port.out16") { portLog.push_back(((a[0].bits&0xffffu)<<32)|(a[1].bits&0xffffu)); return Value(Type::U32,0); }
                        if(e.resolved=="@builtin:port.out8"||e.resolved=="@builtin:port.out32") { portLog.push_back((a[0].bits<<32)|(a[1].bits&0xffffffffu)); return Value(Type::U32,0); }
                        if(e.resolved=="@builtin:cpu.halt") {
                            // the evaluator has no CPU: report where the program stopped, with the serial bytes
                            // (port 0x3F8) and debug-exit (port 0xF4) it wrote, so a fault path is observable.
                            std::string serial,exitv;
                            for(const auto w:portLog) { const auto port=w>>32,val=w&0xffffffffu; if(port==1016)serial.push_back(static_cast<char>(val&255u)); else if(port==244)exitv=std::to_string(val); }
                            fail("E_TARGET_HALT","cpu.halt alcanzado; serial=["+serial+"] debug_exit="+exitv);
                        }
                        if(e.resolved.rfind("@builtin:cpu.",0)==0)fail("E_TARGET_PROFILE","operacion de CPU no ejecutable en el evaluador: "+e.text);
                        if(e.resolved.rfind("@builtin:tls.",0)==0||e.resolved.rfind("@builtin:pcpu.",0)==0)fail("E_TARGET_PROFILE","los bloques por hilo/por CPU dependen de FS/GS y no son ejecutables en el evaluador: "+e.text);
                        // The bytes of a slot-bearing buffer are never visible: every byte-level operation on one is outcome 8 (as in the runtime).
                        if(!slotMeta.empty()&&(e.resolved=="@builtin:buffer.read_u8"||e.resolved=="@builtin:buffer.read_u32le"||e.resolved=="@builtin:buffer.read_u64le"||
                           e.resolved=="@builtin:buffer.write_u8"||e.resolved=="@builtin:buffer.write_u32le"||e.resolved=="@builtin:buffer.write_u64le"||
                           e.resolved=="@builtin:buffer.grow"||e.resolved=="@builtin:buffer.zero"||e.resolved=="@builtin:buffer.freeze")&&!a.empty()&&slotMeta.count(a[0].handle)) {
                            if(e.resolved=="@builtin:buffer.freeze") {   // freeze consumes the buffer: an empty one is freed (nothing is frozen), an occupied one is the E_SLOT_OCCUPIED fault
                                dropSlotBuffer(a[0].handle); auto it=buffers.find(a[0].handle); bufferBytes-=it->second.size(); auditRelease(a[0].handle); buffers.erase(it);
                            }
                            Value r(e.type,0); r.fields.push_back(Value(Type::U32,8)); return r;
                        }
                        if(e.resolved.rfind("@builtin:slots.",0)==0) {
                            const std::string op=e.resolved.substr(15);
                            const std::string tag=slotCallKey(e.text);
                            auto fault=[&](const char* code,const char* what){ fail(code,what); };
                            auto handleOf=[&](uint64_t h,bool releasing=false){ auto b=buffers.find(h); if(b==buffers.end())badBuffer(h,releasing); return b; };
                            // 0 empty, 1 occupied, 2 index out of range, 3 not a slot buffer of this tag
                            auto state=[&](uint64_t h,uint64_t i)->uint32_t{ handleOf(h); auto m=slotMeta.find(h); if(m==slotMeta.end()||m->second.tag!=tag)return 3; if(i>=m->second.occ.size())return 2; if(m->second.occ[static_cast<size_t>(i)])return 1u; return m->second.gen[static_cast<size_t>(i)]>=genMax?4u:0u; };
                            auto word=[&](uint64_t h,uint64_t i){ auto& bytes=buffers.at(h); uint64_t v=0; for(size_t k=0;k<8;++k)v|=static_cast<uint64_t>(bytes[static_cast<size_t>(i)*8+k])<<(8*k); return v; };
                            Value r(e.type,0);
                            auto failure=[&](uint32_t code){ r.fields.push_back(Value(Type::U32,code)); return r; };
                            if(op=="alloc") {
                                const uint64_t cells=a[0].bits;
                                if(acquisitionFails())return failure(3);
                                if(cells>1024u*1024u/8u)return failure(1);
                                if(buffers.size()>=1024||bufferBytes+cells*13u>16u*1024u*1024u)return failure(2);
                                const uint64_t id=nextBuffer;
                                try{ buffers[id]=std::vector<uint8_t>(static_cast<size_t>(cells*8u)); SlotMeta m; m.tag=tag; m.occ.assign(static_cast<size_t>(cells),0); m.gen.assign(static_cast<size_t>(cells),1u); slotMeta[id]=std::move(m); }
                                catch(...){ buffers.erase(id); slotMeta.erase(id); return failure(3); }
                                bufferBytes+=cells*13u; Type bt(Type::Resource); bt.name="Buffer"; Value v(bt); v.handle=nextBuffer++; auditAcquire(v.handle); r.bits=1; r.fields.push_back(v); return r;
                            }
                            if(op=="len"||op=="count") {
                                handleOf(a[0].handle); auto m=slotMeta.find(a[0].handle); if(m==slotMeta.end())return Value(Type::U32,0);
                                return Value(Type::U32,static_cast<uint32_t>(op=="len"?m->second.occ.size():slotsOccupied(m->second)));
                            }
                            if(op=="state")return Value(Type::U32,state(a[0].handle,a[1].bits));
                            if(op=="gen") {   // 0: no such cell (out of range or another type); every take raises it; at the maximum the cell takes no more puts
                                handleOf(a[0].handle); auto m=slotMeta.find(a[0].handle);
                                if(m==slotMeta.end()||m->second.tag!=tag||a[1].bits>=m->second.occ.size())return Value(Type::U32,0);
                                return Value(Type::U32,m->second.gen[static_cast<size_t>(a[1].bits)]);
                            }
                            if(op=="put") {
                                const uint32_t st=state(a[0].handle,a[1].bits);
                                if(st!=0){ r.fields.push_back(a[2]); return r; }   // refused: the caller gets the resource back, nothing changed
                                auto& bytes=buffers.at(a[0].handle); for(size_t k=0;k<8;++k)bytes[static_cast<size_t>(a[1].bits)*8+k]=static_cast<uint8_t>((a[2].handle>>(8*k))&255u);
                                slotMeta.at(a[0].handle).occ[static_cast<size_t>(a[1].bits)]=1; r.bits=1; r.fields.push_back(Value(Type::U32,a[1].bits)); return r;
                            }
                            if(op=="take") {
                                const uint32_t st=state(a[0].handle,a[1].bits);
                                if(st!=1)return failure(st==0?1u:st);
                                Value v(e.type.parts.at(0)); v.handle=word(a[0].handle,a[1].bits);
                                auto& bytes=buffers.at(a[0].handle); std::memset(bytes.data()+static_cast<size_t>(a[1].bits)*8,0,8);
                                slotMeta.at(a[0].handle).occ[static_cast<size_t>(a[1].bits)]=0; { auto& g=slotMeta.at(a[0].handle).gen[static_cast<size_t>(a[1].bits)]; if(g<genMax)++g; } r.bits=1; r.fields.push_back(v); return r;
                            }
                            if(op=="borrow"||op=="borrow_mut") {
                                if(state(a[0].handle,a[1].bits)!=1)fault("E_SLOT_STATE","slots.borrow sobre una celda vacia o ajena: compruebe slots.state antes");
                                Value v(e.type); v.handle=word(a[0].handle,a[1].bits); return v;
                            }
                            if(op=="grow") {
                                auto b=handleOf(a[0].handle); auto m=slotMeta.find(a[0].handle); if(m==slotMeta.end())return failure(8);
                                const uint64_t cells=a[1].bits, old=m->second.occ.size();
                                if(acquisitionFails())return failure(3);
                                if(cells<old)return failure(4);
                                if(cells>1024u*1024u/8u)return failure(1);
                                if(cells!=old){
                                    if(bufferBytes+(cells-old)*13u>16u*1024u*1024u)return failure(2);
                                    try{ b->second.resize(static_cast<size_t>(cells*8u)); m->second.occ.resize(static_cast<size_t>(cells),0); m->second.gen.resize(static_cast<size_t>(cells),1u); }catch(...){ return failure(3); }
                                    bufferBytes+=(cells-old)*13u;
                                }
                                r.bits=1; r.fields.push_back(Value(Type::U32,cells)); return r;
                            }
                            if(op=="release") {   // refused (the buffer comes back) while a cell is occupied; otherwise freed
                                handleOf(a[0].handle,true); auto m=slotMeta.find(a[0].handle);
                                if(m!=slotMeta.end()&&slotsOccupied(m->second)!=0){ r.fields.push_back(a[0]); return r; }
                                auto b=handleOf(a[0].handle,true); dropSlotBuffer(a[0].handle); bufferBytes-=b->second.size(); auditRelease(a[0].handle); buffers.erase(b);
                                r.bits=1; r.fields.push_back(Value(Type::U32,0)); return r;
                            }
                            fail("E_INTERNAL","primitiva de slots sin evaluador: "+e.text);
                        }
                        if(e.resolved=="@builtin:buffer.len") { auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false); return Value(Type::U32,static_cast<uint32_t>(it->second.size())); }
                        if(e.resolved=="@builtin:buffer.read_u32le"||e.resolved=="@builtin:buffer.read_u64le") { const bool wide=e.resolved=="@builtin:buffer.read_u64le"; const size_t width=wide?8:4; Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false); const size_t n=it->second.size(); if(a[1].bits>n||width>n-a[1].bits){r.fields.push_back(Value(Type::U32,1));return r;} uint64_t v=0; for(size_t k=0;k<width;++k)v|=static_cast<uint64_t>(it->second[a[1].bits+k])<<(8*k); r.bits=1;r.fields.push_back(Value(wide?Type::U64:Type::U32,v));return r; }
                        if(e.resolved=="@builtin:buffer.write_u32le"||e.resolved=="@builtin:buffer.write_u64le") { const bool wide=e.resolved=="@builtin:buffer.write_u64le"; const size_t width=wide?8:4; Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false); const size_t n=it->second.size(); if(a[1].bits>n||width>n-a[1].bits){r.fields.push_back(Value(Type::U32,1));return r;} uint64_t v=a[2].bits; for(size_t k=0;k<width;++k)it->second[a[1].bits+k]=static_cast<uint8_t>((v>>(8*k))&255u); r.bits=1;r.fields.push_back(Value(Type::U32,1));return r; }
                        if(e.resolved=="@builtin:buffer.read_u8") { Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false); if(a[1].bits>=it->second.size()){r.fields.push_back(Value(Type::U32,1));return r;} r.bits=1;r.fields.push_back(Value(Type::U32,it->second[a[1].bits]));return r; }
                        if(e.resolved=="@builtin:buffer.write_u8") { Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false); if(a[1].bits>=it->second.size()||a[2].bits>255){r.fields.push_back(Value(Type::U32,1));return r;} it->second[a[1].bits]=(uint8_t)a[2].bits; r.bits=1;r.fields.push_back(Value(Type::U32,1));return r; }
                        if(e.resolved=="@builtin:buffer.grow") {
                            Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false);
                            const uint64_t n=a[1].bits; const uint64_t old=it->second.size();
                            if(acquisitionFails()){r.fields.push_back(Value(Type::U32,3));return r;}
                            if(n<old){r.fields.push_back(Value(Type::U32,4));return r;}
                            if(n>1024u*1024u){r.fields.push_back(Value(Type::U32,1));return r;}
                            if(n!=old){
                                if(bufferBytes+(n-old)>16u*1024u*1024u){r.fields.push_back(Value(Type::U32,2));return r;}
                                try{ it->second.resize(n); }catch(...){r.fields.push_back(Value(Type::U32,3));return r;}
                                bufferBytes+=n-old;
                            }
                            r.bits=1;r.fields.push_back(Value(Type::U32,n));return r;
                        }
                        if(e.resolved=="@builtin:buffer.zero") {
                            Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,false);
                            const uint64_t n=it->second.size(); if(a[1].bits>n||a[2].bits>n-a[1].bits){r.fields.push_back(Value(Type::U32,1));return r;}
                            if(a[2].bits!=0)std::memset(it->second.data()+a[1].bits,0,static_cast<size_t>(a[2].bits));
                            r.bits=1;r.fields.push_back(Value(Type::U32,1));return r;
                        }
                        if(e.resolved=="@builtin:buffer.freeze") { Value r(e.type,0); auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,true); try{ std::string data(reinterpret_cast<const char*>(it->second.data()),it->second.size()); r.bits=1;r.fields.push_back(Value(Type::Bytes,std::move(data))); bufferBytes-=it->second.size(); auditRelease(a[0].handle); buffers.erase(it); }catch(...){r.fields.push_back(Value(Type::U32,1));} return r; }
                        if(e.resolved=="@builtin:buffer.release") { auto it=buffers.find(a[0].handle); if(it==buffers.end())badBuffer(a[0].handle,true); dropSlotBuffer(a[0].handle); bufferBytes-=it->second.size();auditRelease(a[0].handle);buffers.erase(it);return Value(Type::U32,0); }
                        if(e.resolved=="@builtin:char.from_u32") {
                            Value r(e.type,0); const auto cp=static_cast<uint32_t>(a[0].bits);
                            if(!validUnicodeScalar(cp)){r.fields.push_back(Value(Type::U32,1));return r;}
                            r.bits=1;r.fields.push_back(Value(Type::Char,cp));return r;
                        }
                        if(e.resolved=="@builtin:char.codepoint") return Value(Type::U32,a[0].bits);
                        if(e.resolved=="@builtin:text.from_char") {
                            Value r(e.type,0); const auto cp=static_cast<uint32_t>(a[0].bits);
                            if(cp==0u){r.fields.push_back(Value(Type::U32,1));return r;}
                            r.bits=1;r.fields.push_back(Value(Type::Text,encodeUnicodeScalar(cp)));return r;
                        }
                        if(e.resolved=="@builtin:text.equals") return Value(Type::Bool,a[0].text==a[1].text);
                        if(e.resolved=="@builtin:text.byte_len") return Value(Type::U32,static_cast<uint32_t>(a[0].text.size()));
                        if(e.resolved=="@builtin:text.scalar_len") return Value(Type::U32,utf8ScalarCount(a[0].text));
                        if(e.resolved=="@builtin:text.scalar_at") {
                            Value r(e.type,0); uint32_t cp=0;
                            if(!utf8ScalarAt(a[0].text,static_cast<uint32_t>(a[1].bits),cp)){r.fields.push_back(Value(Type::U32,1));return r;}
                            r.bits=1;r.fields.push_back(Value(Type::Char,cp));return r;
                        }
                        if(e.resolved=="@builtin:text.len") return Value(Type::U32,static_cast<uint32_t>(a[0].text.size()));
                        if(e.resolved=="@builtin:text.concat") {
                            if(a[0].text.size()+a[1].text.size()>OMNI_TEXT_VALUE_LIMIT_BYTES)fail("E_TEXT_LIMIT","Text concat excede limite de 1 MiB");
                            return Value(Type::Text,a[0].text+a[1].text);
                        }
                        if(e.resolved=="@builtin:host.read"||e.resolved=="@builtin:file.read_text") {
                            auto denied=[&](uint32_t code){Value r(e.type,0);r.fields.push_back(Value(Type::U32,code));return r;};
                            const uint64_t limit=e.resolved=="@builtin:host.read"?a[1].bits:OMNI_TEXT_VALUE_LIMIT_BYTES;
                            if(limit==0)return denied(2);
                            if(limit>OMNI_TEXT_VALUE_LIMIT_BYTES)return denied(5);
                            if(!hostPolicy)return denied(1);
                            std::error_code ec;
                            const auto lexical=std::filesystem::absolute(a[0].text,ec).lexically_normal();
                            if(ec||!hostPolicy->allows("fs.read",lexical.generic_string(),0,1000000-fuel,hostPolicy->generation))return denied(1);
                            const auto canonical=std::filesystem::weakly_canonical(lexical,ec);
                            if(ec)return denied(3);
                            if(!hostPolicy->allows("fs.read",canonical.generic_string(),0,1000000-fuel,hostPolicy->generation))return denied(1);
                            std::ifstream file(canonical,std::ios::binary);
                            if(!file)return denied(3);
                            std::string data(static_cast<size_t>(limit)+1u,'\0');
                            file.read(data.data(),static_cast<std::streamsize>(data.size()));
                            const auto count=file.gcount();
                            if(count<0)return denied(4);
                            data.resize(static_cast<size_t>(count));
                            if(data.size()>limit)return denied(5);
                            if(!file.eof()&&file.fail())return denied(4);
                            if(!hostPolicy->allows("fs.read",canonical.generic_string(),data.size(),1000000-fuel,hostPolicy->generation))return denied(1);
                            Value result(e.type,1);
                            if(e.resolved=="@builtin:file.read_text") {
                                try { validateUTF8(data); } catch(const Error&){ return denied(2); }
                                result.fields.push_back(Value(Type::Text,std::move(data)));
                            } else result.fields.push_back(Value(Type::Bytes,std::move(data)));
                            return result;
                        }
                        if(e.resolved=="@builtin:host.write"||e.resolved=="@builtin:file.write_text") {
                            auto denied=[&](uint32_t code){Value r(e.type,0);r.fields.push_back(Value(Type::U32,code));return r;};
                            if(a[1].text.size()>OMNI_TEXT_VALUE_LIMIT_BYTES)return denied(5);
                            if(!hostPolicy)return denied(1);
                            std::error_code ec;
                            const auto lexical=std::filesystem::absolute(a[0].text,ec).lexically_normal();
                            if(ec||!hostPolicy->allows("fs.write",lexical.generic_string(),a[1].text.size(),1000000-fuel,hostPolicy->generation))return denied(1);
                            const auto canonical=std::filesystem::weakly_canonical(lexical,ec);
                            if(ec)return denied(3);
                            if(!hostPolicy->allows("fs.write",canonical.generic_string(),a[1].text.size(),1000000-fuel,hostPolicy->generation))return denied(1);
                            std::ofstream file(canonical,std::ios::binary|std::ios::trunc);
                            if(!file)return denied(3);
                            file.write(a[1].text.data(),static_cast<std::streamsize>(a[1].text.size()));
                            if(!file.flush()||!file)return denied(4);
                            Value result(e.type,1); result.fields.push_back(Value(Type::U32,static_cast<uint32_t>(a[1].text.size()))); return result;
                        }
                        if(e.resolved=="@builtin:host.process") {
                            auto failure=[&](uint32_t code){Value r(e.type,0);r.fields.push_back(Value(Type::U32,code));return r;};
                            if(a[2].bits==0||a[2].bits>OMNI_TEXT_VALUE_LIMIT_BYTES)return failure(a[2].bits==0?2u:5u);
                            if(a[3].bits==0)return failure(6);
                            if(a[1].text.size()>OMNI_TEXT_VALUE_LIMIT_BYTES)return failure(5);
                            if(!hostPolicy)return failure(1);
                            std::error_code ec;
                            const auto adapter=std::filesystem::canonical(std::filesystem::absolute(a[0].text,ec),ec);
                            if(ec)return failure(1);
                            const auto authorityBytes=std::max<uint64_t>(a[1].text.size(),a[2].bits);
                            if(!hostPolicy->allows("process.spawn",adapter.generic_string(),authorityBytes,1000000-fuel,hostPolicy->generation))return failure(1);
                            const auto result=runHostProcess(adapter.generic_string(),a[1].text,static_cast<uint32_t>(a[2].bits),static_cast<uint32_t>(a[3].bits));
                            if(result.code)return failure(result.code);
                            Value success(e.type,1);success.fields.push_back(Value(Type::Bytes,result.payload));return success;
                        }
                        if(e.resolved=="@builtin:host.tcp") {
                            auto failure=[&](uint32_t code){Value r(e.type,0);r.fields.push_back(Value(Type::U32,code));return r;};
                            if(a[2].bits==0||a[2].bits>OMNI_TEXT_VALUE_LIMIT_BYTES)return failure(a[2].bits==0?2u:5u);
                            if(a[3].bits==0)return failure(6);
                            if(a[1].text.size()>OMNI_TEXT_VALUE_LIMIT_BYTES)return failure(5);
                            if(!hostPolicy)return failure(1);
                            const auto authorityBytes=std::max<uint64_t>(a[1].text.size(),a[2].bits);
                            if(!hostPolicy->allows("net.connect",a[0].text,authorityBytes,1000000-fuel,hostPolicy->generation))return failure(1);
                            const auto result=runHostTcp(a[0].text,a[1].text,static_cast<uint32_t>(a[2].bits),static_cast<uint32_t>(a[3].bits));
                            if(result.code)return failure(result.code);
                            Value success(e.type,1);success.fields.push_back(Value(Type::Bytes,result.payload));return success;
                        }
                        if(e.resolved=="@builtin:host.ffi") {
                            auto failure=[&](uint32_t code){Value r(e.type,0);r.fields.push_back(Value(Type::U32,code));return r;};
                            if(a[2].bits==0||a[2].bits>OMNI_TEXT_VALUE_LIMIT_BYTES)return failure(a[2].bits==0?2u:5u);
                            if(a[1].text.size()>OMNI_TEXT_VALUE_LIMIT_BYTES)return failure(5);
                            if(!hostPolicy)return failure(1);
                            std::error_code ec;
                            const auto library=std::filesystem::canonical(std::filesystem::absolute(a[0].text,ec),ec);
                            if(ec)return failure(1);
                            const auto authorityBytes=std::max<uint64_t>(a[1].text.size(),a[2].bits);
                            if(!hostPolicy->allows("ffi.call",library.generic_string(),authorityBytes,1000000-fuel,hostPolicy->generation))return failure(1);
                            const auto result=runHostFfi(library.generic_string(),a[1].text,static_cast<uint32_t>(a[2].bits));
                            if(result.code)return failure(result.code);
                            Value success(e.type,1);success.fields.push_back(Value(Type::Bytes,result.payload));return success;
                        }
                        return call(e.resolved,a);
                    }
                    case Expr::ClosureCall: {
                        std::vector<Value>a;
                        for(auto binding:e.closureCaptureBindings)a.push_back(env.at(static_cast<size_t>(binding)));
                        for(const auto& v:e.args)a.push_back(expr(v,env));
                        return call(e.resolved,a);
                    }
                    case Expr::Unary:
                        if(e.text=="!") return Value(Type::Bool,!expr(e.args[0],env).bits);
                        if(e.text=="-") {
                            if(isFloat(e.type)) {
                                auto v=expr(e.args[0],env);
                                return Value(v.type,floatBits(v.type,-floatValue(v.type,v.bits)));
                            }
                            if(e.args[0].kind==Expr::Number) {
                                auto t=e.type; auto mag=e.args[0].value;
                                if(integerWidth(t)==64&&mag==(uint64_t(1)<<63))return Value(t,uint64_t(1)<<63);
                                return Value(t,encodeSigned(t,-static_cast<int64_t>(mag)));
                            }
                            auto v=expr(e.args[0],env); auto x=signedBits(v.type,v.bits);
                            if(x==integerMinSigned(v.type))fail("E_OVERFLOW","negacion fuera de "+typeName(v.type));
                            return Value(v.type,encodeSigned(v.type,-x));
                        }
                        fail("E_INTERNAL","unario sin evaluacion");
                    case Expr::Binary: {
                        auto av=expr(e.args[0],env); auto a=av.bits;
                        if(e.text=="&&"&&!a)return  {
                            Type::Bool,0
                        };
                        if(e.text=="||"&&a)return  {
                            Type::Bool,1
                        };
                        auto bv=expr(e.args[1],env); auto b=bv.bits;
                        uint64_t r=0;
                        if(av.type==Type::Char){
                            if(e.text=="==")r=a==b;
                            else if(e.text=="!=")r=a!=b;
                            else if(e.text=="<")r=a<b;
                            else if(e.text=="<=")r=a<=b;
                            else if(e.text==">")r=a>b;
                            else if(e.text==">=")r=a>=b;
                            else fail("E_INTERNAL","binario Char sin evaluacion");
                            return {e.type,r};
                        }
                        if(av.type.kind==Type::Bool&&(e.text=="=="||e.text=="!=")) {   // the checker admits bool equality and the native code computes it; the evaluator did not (E_TYPE "tipo no entero")
                            const bool same=(a!=0)==(b!=0);
                            return {e.type,(e.text=="==")==same?1u:0u};
                        }
                        if(isFloat(av.type)) {
                            const double x=floatValue(av.type,a), y=floatValue(av.type,b);
                            if(e.text=="+"||e.text=="-"||e.text=="*"||e.text=="/")r=floatBinaryBits(av.type,e.text,a,b);
                            else if(e.text=="==")r=x==y;
                            else if(e.text=="!=")r=x!=y;
                            else if(e.text=="<")r=x<y;
                            else if(e.text=="<=")r=x<=y;
                            else if(e.text==">")r=x>y;
                            else if(e.text==">=")r=x>=y;
                            else fail("E_INTERNAL","binario float sin evaluacion");
                            return {e.type,r};
                        }
                        if(e.text=="+"||e.text=="-"||e.text=="*"||e.text=="/"||e.text=="%")r=checkedIntOp(av.type,e.text,a,b);
                        else if(e.text=="+%"||e.text=="-%"||e.text=="*%")r=wrappingIntOp(av.type,e.text,a,b);
                        else if(e.text=="+|"||e.text=="-|"||e.text=="*|")r=saturatingIntOp(av.type,e.text,a,b);
                        else if(e.text=="==")r=(a&intMask(av.type))==(b&intMask(av.type));
                        else if(e.text=="!=")r=(a&intMask(av.type))!=(b&intMask(av.type));
                        else if(e.text=="<")r=isSignedInteger(av.type)?signedBits(av.type,a)<signedBits(av.type,b):(a&intMask(av.type))<(b&intMask(av.type));
                        else if(e.text=="<=")r=isSignedInteger(av.type)?signedBits(av.type,a)<=signedBits(av.type,b):(a&intMask(av.type))<=(b&intMask(av.type));
                        else if(e.text==">")r=isSignedInteger(av.type)?signedBits(av.type,a)>signedBits(av.type,b):(a&intMask(av.type))>(b&intMask(av.type));
                        else if(e.text==">=")r=isSignedInteger(av.type)?signedBits(av.type,a)>=signedBits(av.type,b):(a&intMask(av.type))>=(b&intMask(av.type));
                        else if(e.text=="&&")r=a&&b;
                        else if(e.text=="||")r=a||b;
                        else fail("E_INTERNAL","binario sin evaluacion");
                        return  {
                            e.type,r
                        };
                    }
                    case Expr::RecordInit: {
                        Value v(e.type);
                        v.fields.resize(e.args.size());
                        for(size_t i=0; i<e.args.size(); i++)v.fields[static_cast<size_t>(e.indices[i])]=expr(e.args[i],env);
                        return v;
                    }
                    case Expr::Field: {
                        auto v=expr(e.args[0],env);
                        return v.fields.at(static_cast<size_t>(e.binding));
                    }
                    case Expr::Ok:case Expr::Err: {
                        Value v(e.type,e.kind==Expr::Ok?1:0);
                        v.fields.push_back(expr(e.args[0],env));
                        return v;
                    }
                    case Expr::Some: { Value v(e.type,1); v.fields.push_back(expr(e.args[0],env)); return v; }
                    case Expr::None: return Value(e.type,0);
                    case Expr::Variant: { Value v(e.type,static_cast<uint64_t>(e.binding)); if(!e.args.empty())v.fields.push_back(expr(e.args[0],env)); return v; }
                    case Expr::Join: {
                        auto future=env.at(static_cast<size_t>(e.binding));
                        if(future.type.kind!=Type::Future||future.fields.size()!=1)fail("E_TASK_HANDLE","Future invalido en evaluator");
                        Value result(e.type,1); result.fields.push_back(future.fields[0]);
                        return result;
                    }
                    case Expr::Cancel: {
                        auto future=env.at(static_cast<size_t>(e.binding));
                        if(future.type.kind!=Type::Future)fail("E_TASK_HANDLE","Future invalido en evaluator");
                        Value result(e.type,1); result.fields.push_back(Value(Type::U32,1));
                        return result;
                    }
                    case Expr::Deadline: {
                        auto future=env.at(static_cast<size_t>(e.binding));
                        if(future.type.kind!=Type::Future||future.fields.size()!=1)fail("E_TASK_HANDLE","Future invalido en evaluator");
                        auto ticks=expr(e.args.at(0),env).bits; Value result(e.type,ticks?1:0);
                        if(ticks)result.fields.push_back(future.fields[0]); else result.fields.push_back(Value(Type::U32,4));
                        return result;
                    }
                    case Expr::Channel: {
                        const auto capacity=expr(e.args[0],env).bits;
                        if(capacity==0||capacity>1024)fail("E_CHANNEL_CAPACITY","capacity invalida en evaluator");
                        Value stream(e.type); stream.handle=nextChannel;
                        channels.emplace(nextChannel++,ChannelState{e.type.parts.at(0),static_cast<uint32_t>(capacity),false,{}});
                        return stream;
                    }
                    case Expr::Send: {
                        auto& stream=env.at(static_cast<size_t>(e.binding)); auto it=channels.find(stream.handle);
                        if(it==channels.end())fail("E_CHANNEL_HANDLE","Stream invalido en evaluator");
                        Value result(e.type,0);
                        if(it->second.closed)result.fields.push_back(Value(Type::U32,2));
                        else if(it->second.queue.size()>=it->second.capacity)result.fields.push_back(Value(Type::U32,3));
                        else { it->second.queue.push_back(expr(e.args[0],env)); result.bits=1; result.fields.push_back(Value(Type::U32,0)); }
                        return result;
                    }
                    case Expr::Receive: {
                        auto& stream=env.at(static_cast<size_t>(e.binding)); auto it=channels.find(stream.handle);
                        if(it==channels.end())fail("E_CHANNEL_HANDLE","Stream invalido en evaluator");
                        Value option(e.type.parts.at(0),0); Value result(e.type,1);
                        if(!it->second.queue.empty()){ option.bits=1; option.fields.push_back(std::move(it->second.queue.front())); it->second.queue.pop_front(); }
                        else if(!it->second.closed){ result.bits=0; result.fields.push_back(Value(Type::U32,3)); return result; }
                        result.fields.push_back(std::move(option)); return result;
                    }
                    case Expr::Try: fail("E_INTERNAL","? sin bajar antes de evaluar",e.loc);
                    case Expr::Close: {
                        auto& stream=env.at(static_cast<size_t>(e.binding)); auto it=channels.find(stream.handle);
                        if(it==channels.end())fail("E_CHANNEL_HANDLE","Stream invalido en evaluator");
                        it->second.closed=true; Value result(e.type,1); result.fields.push_back(Value(Type::U32,0)); return result;
                    }
                }
                fail("E_INTERNAL","expresion sin evaluacion");
            }
            void print(const std::string&s) {
                if(output.size()+s.size()+1>1024*1024)fail("E_OUTPUT_LIMIT","salida excede limite");
                output+=s;
                output+='\n';
            }
            void block(const std::vector<Stmt>&b,std::vector<Value>&env,const std::vector<int>& extraBindings={}) {
                const auto localBindings=scopeBindings(b,extraBindings);
                try {
                for(auto&s:b) {
                    tick();
                    switch(s.kind) {
                        case Stmt::Let:case Stmt::Var:case Stmt::Assign:env.at(static_cast<size_t>(s.binding))=expr(s.expr,env);
                        break;
                        case Stmt::Destructure: {
                            auto v=expr(s.expr,env);
                            if(v.fields.size()!=s.bindings.size())fail("E_INTERNAL","tuple destructuring evaluator arity mismatch");
                            for(size_t i=0;i<s.bindings.size();++i)if(s.bindings[i]>=0)
                                env.at(static_cast<size_t>(s.bindings[i]))=v.fields[i];
                            break;
                        }
                        case Stmt::TaskScope: block(s.body,env); break;
                        case Stmt::Spawn: {
                            // The A85 reference scheduler has no yielding expression
                            // yet: spawning evaluates one transferable scalar child in
                            // deterministic FIFO order and stores its terminal value.
                            Type futureType(Type::Future); futureType.parts.push_back(s.expr.type);
                            Value future(std::move(futureType));
                            future.fields.push_back(expr(s.expr,env));
                            env.at(static_cast<size_t>(s.binding))=std::move(future);
                            break;
                        }
                        case Stmt::Return:throw Returned {
                            expr(s.expr,env)
                        };
                        case Stmt::Break: throw LoopBreak{};
                        case Stmt::Continue: throw LoopContinue{};
                        case Stmt::If:if(expr(s.expr,env).bits)block(s.body,env);
                        else block(s.other,env);
                        break;
                        case Stmt::Loop:
                            while(expr(s.expr,env).bits){
                                try { block(s.body,env); }
                                catch(const LoopContinue&){ continue; }
                                catch(const LoopBreak&){ break; }
                            }
                        break;
                        case Stmt::ForEach: {
                            auto seq=expr(s.expr,env);
                            if(s.iteratorProtocol==Stmt::IteratorRange){
                                if(seq.type.kind!=Type::Range)fail("E_INTERNAL","resolved Range iteration protocol has incompatible type",s.loc);
                                if(seq.fields.size()!=2)fail("E_INTERNAL","Range evaluator requiere start/end",s.loc);
                                const uint64_t start=seq.fields[0].bits;
                                const uint64_t end=seq.fields[1].bits;
                                const bool inclusive=seq.bits!=0;
                                if(start<=end){
                                    for(uint64_t current=start; inclusive?current<=end:current<end; ++current){
                                        if(s.binding>=0)env.at(static_cast<size_t>(s.binding))=Value(Type::U32,current);
                                        bool stop=false;
                                        try { block(s.body,env); }
                                        catch(const LoopContinue&) { }
                                        catch(const LoopBreak&) { stop=true; }
                                        if(stop)break;
                                    }
                                }
                            } else if(s.iteratorProtocol==Stmt::IteratorArray||s.iteratorProtocol==Stmt::IteratorView) {
                                if((s.iteratorProtocol==Stmt::IteratorArray&&seq.type.kind!=Type::Array)||(s.iteratorProtocol==Stmt::IteratorView&&seq.type.kind!=Type::View))fail("E_INTERNAL","resolved collection iteration protocol has incompatible type",s.loc);
                                for(const auto& item:seq.fields){
                                    if(s.binding>=0)env.at(static_cast<size_t>(s.binding))=item;
                                    try { block(s.body,env); }
                                    catch(const LoopContinue&){ continue; }
                                    catch(const LoopBreak&){ break; }
                                }
                            } else fail("E_INTERNAL","unresolved static iteration protocol",s.loc);
                            break;
                        }
                        case Stmt::Print: {
                            auto v=expr(s.expr,env);
                            if(v.type==Type::Text)print(v.text);
                            else if(v.type==Type::Bool)print(v.bits?"true":"false");
                            else if(v.type==Type::Char)print(encodeUnicodeScalar(static_cast<uint32_t>(v.bits)));
                            else if(isFloat(v.type)) {
                                char buf[128];
                                if(v.type.kind==Type::F32) {
                                    auto x=std::bit_cast<float>(static_cast<uint32_t>(v.bits));
                                    auto r=std::to_chars(buf,buf+sizeof(buf),x,std::chars_format::general,std::numeric_limits<float>::max_digits10);
                                    if(r.ec!=std::errc{})fail("E_INTERNAL","print f32");
                                    print(std::string(buf,r.ptr));
                                } else {
                                    auto x=std::bit_cast<double>(v.bits);
                                    auto r=std::to_chars(buf,buf+sizeof(buf),x,std::chars_format::general,std::numeric_limits<double>::max_digits10);
                                    if(r.ec!=std::errc{})fail("E_INTERNAL","print f64");
                                    print(std::string(buf,r.ptr));
                                }
                            }
                            else if(isSignedInteger(v.type))print(std::to_string(signedBits(v.type,v.bits)));
                            else print(std::to_string(v.bits&intMask(v.type)));
                            break;
                        }
                        case Stmt::PrintText:print(s.text);
                        break;
                        case Stmt::Match: {
                            auto v=expr(s.expr,env);
                            const int bind=v.bits?s.binding:s.otherBinding;
                            if(bind>=0)env.at(static_cast<size_t>(bind))=v.fields[0];
                            if(v.bits)block(s.body,env,{s.binding});
                            else block(s.other,env,{s.otherBinding});
                            break;
                        }
                        case Stmt::MatchOption: {
                            auto v=expr(s.expr,env);
                            if(v.bits){ if(s.binding>=0)env.at(static_cast<size_t>(s.binding))=v.fields[0]; block(s.body,env,{s.binding}); }
                            else block(s.other,env);
                            break;
                        }
                        case Stmt::MatchEnum: {
                            auto v=expr(s.expr,env); auto tag=static_cast<int>(v.bits); bool hit=false;
                            for(size_t ai=0;ai<s.arms.size();++ai)if(s.armVariantIndices[ai]==tag){
                                if(s.armBindings[ai]>=0){ if(v.fields.empty())fail("E_INTERNAL","enum payload ausente en evaluator",s.loc); env.at(static_cast<size_t>(s.armBindings[ai]))=v.fields[0]; }
                                block(s.arms[ai],env,{s.armBindings[ai]}); hit=true; break;
                            }
                            if(!hit)fail("E_INTERNAL","tag enum no cubierto tras validacion",s.loc);
                            break;
                        }
                    }
                }
                }
                catch(...) {
                    cleanupBindings(env,localBindings);
                    throw;
                }
                cleanupBindings(env,localBindings);
            }
            public: explicit Evaluator(const Program&x,const HostPolicy* policy):p(x),hostPolicy(policy) {
                for(auto&f:p.functions)funcs[f.key]=&f;
                if(const char* a=std::getenv("OMNI_RESOURCE_AUDIT"))auditOn=std::string(a)=="1";
                if(const char* g=std::getenv("OMNI_SLOT_GEN_MAX")) { char* end=nullptr; const unsigned long long v=std::strtoull(g,&end,10); if(end&&*end==0&&*g!=0&&v>=2&&v<=UINT32_MAX)genMax=static_cast<uint32_t>(v); }
                if(const char* f=std::getenv("OMNI_FAIL_AT")) { char* end=nullptr; const unsigned long long v=std::strtoull(f,&end,10); if(end&&*end==0&&*f!=0)failAt=v; }
            }
            ~Evaluator() { if(auditOn)std::fprintf(stderr,"audit summary acquired=%u released=%u live=%zu\n",auditAcq,auditRel,buffers.size()); }
            Value value(const std::string& key) { return call(key,{}); }
            // CP-10 / MN-04: the lane-by-lane model of the vector intrinsics (the native lowering uses LLVM vectors; the two must agree).
            Value simd(const Expr& e,const std::vector<Value>& a) {
                const std::string op=e.resolved.substr(14);
                const auto ltp=e.text.find('<'); const std::string inner=e.text.substr(ltp+1,e.text.size()-ltp-2);
                std::string k1=inner,k2; if(const auto c=inner.find(','); c!=std::string::npos){ k1=inner.substr(0,c); k2=inner.substr(c+1); }
                auto find=[&](const std::string& k)->const RecordDef& { for(const auto& r:p.records)if(r.key==k)return r; fail("E_INTERNAL","struct sin definicion: "+k); };
                const RecordDef& vr=find(k1); const Type lane=vr.fields.at(0).type; const size_t n=vr.fields.size();
                Type vt(Type::Record); vt.name=vr.name; vt.key=k1;
                auto vec=[&](std::vector<Value> fs){ Value v(vt); v.fields=std::move(fs); return v; };
                auto maskType=[&]{ const auto& mr=find(k2); Type t(Type::Record); t.name=mr.name; t.key=k2; return t; };
                const bool real=isFloat(lane);
                auto lanes=[&](const Value& v,size_t i){ return v.fields.at(i).bits; };
                if(op=="splat") return vec(std::vector<Value>(n,Value(lane,a[0].bits)));
                if(op=="add"||op=="sub"||op=="mul"||op=="div") {
                    const std::string sym=op=="add"?"+":(op=="sub"?"-":(op=="mul"?"*":"/")); std::vector<Value> fs;
                    for(size_t i=0;i<n;++i)fs.push_back(Value(lane,real?floatBinaryBits(lane,sym,lanes(a[0],i),lanes(a[1],i)):wrappingIntOp(lane,sym+"%",lanes(a[0],i),lanes(a[1],i))));
                    return vec(std::move(fs));
                }
                if(op=="and"||op=="or"||op=="xor") {
                    std::vector<Value> fs;
                    for(size_t i=0;i<n;++i){ const uint64_t x=lanes(a[0],i)&intMask(lane), y=lanes(a[1],i)&intMask(lane); fs.push_back(Value(lane,op=="and"?(x&y):(op=="or"?(x|y):(x^y)))); }
                    return vec(std::move(fs));
                }
                if(op=="eq"||op=="ne"||op=="lt"||op=="le"||op=="gt"||op=="ge") {
                    Value m(maskType());
                    for(size_t i=0;i<n;++i) {
                        const uint64_t x=lanes(a[0],i), y=lanes(a[1],i); bool r=false;
                        if(real) {
                            const double fx=floatValue(lane,x), fy=floatValue(lane,y);
                            r=op=="eq"?fx==fy:(op=="ne"?fx!=fy:(op=="lt"?fx<fy:(op=="le"?fx<=fy:(op=="gt"?fx>fy:fx>=fy))));
                        } else if(isSignedInteger(lane)) {
                            const int64_t sx=signedBits(lane,x), sy=signedBits(lane,y);
                            r=op=="eq"?sx==sy:(op=="ne"?sx!=sy:(op=="lt"?sx<sy:(op=="le"?sx<=sy:(op=="gt"?sx>sy:sx>=sy))));
                        } else {
                            const uint64_t ux=x&intMask(lane), uy=y&intMask(lane);
                            r=op=="eq"?ux==uy:(op=="ne"?ux!=uy:(op=="lt"?ux<uy:(op=="le"?ux<=uy:(op=="gt"?ux>uy:ux>=uy))));
                        }
                        m.fields.push_back(Value(Type::Bool,r?1:0));
                    }
                    return m;
                }
                if(op=="select") {
                    std::vector<Value> fs;
                    for(size_t i=0;i<n;++i)fs.push_back(a[0].fields.at(i).bits?a[1].fields.at(i):a[2].fields.at(i));
                    return vec(std::move(fs));
                }
                if(op=="mask_and"||op=="mask_or"||op=="mask_xor"||op=="mask_not") {
                    Value m(vt);
                    for(size_t i=0;i<n;++i) {
                        const bool x=a[0].fields.at(i).bits!=0, y=op=="mask_not"?false:a[1].fields.at(i).bits!=0;
                        m.fields.push_back(Value(Type::Bool,(op=="mask_and"?(x&&y):(op=="mask_or"?(x||y):(op=="mask_xor"?(x!=y):!x)))?1:0));
                    }
                    return m;
                }
                if(op=="any"||op=="all"||op=="bitmask") {
                    uint64_t bits=0; size_t on=0;
                    for(size_t i=0;i<n;++i)if(a[0].fields.at(i).bits){ bits|=uint64_t(1)<<i; ++on; }
                    if(op=="any")return Value(Type::Bool,on>0?1:0);
                    if(op=="all")return Value(Type::Bool,on==n?1:0);
                    return Value(Type::U32,bits);
                }
                if(op=="reduce_add") {
                    uint64_t acc=lanes(a[0],0);
                    for(size_t i=1;i<n;++i)acc=real?floatBinaryBits(lane,"+",acc,lanes(a[0],i)):wrappingIntOp(lane,"+%",acc,lanes(a[0],i));
                    return Value(lane,acc);
                }
                // load / store: lane i at address + i * width, little endian, over the evaluator's sparse memory
                const bool aligned=op=="load_aligned"||op=="store_aligned";
                const uint64_t at=a[0].bits;
                if(at==0||(aligned&&(at&15)!=0))fail("E_LAYOUT","acceso simd nulo o desalineado en el evaluador: "+e.text);
                const size_t w=real?(lane.kind==Type::F32?4:8):integerWidth(lane)/8;
                if(op=="load"||op=="load_aligned") {
                    std::vector<Value> fs;
                    for(size_t i=0;i<n;++i){ uint64_t bits=0; for(size_t b=0;b<w;++b){ auto it=rawMemory.find(at+i*w+b); if(it!=rawMemory.end())bits|=static_cast<uint64_t>(it->second)<<(8*b); } fs.push_back(Value(lane,bits)); }
                    return vec(std::move(fs));
                }
                for(size_t i=0;i<n;++i)for(size_t b=0;b<w;++b)rawMemory[at+i*w+b]=static_cast<uint8_t>((a[1].fields.at(i).bits>>(8*b))&255u);
                return Value(Type::U32,0);
            }
            EvalResult run(const std::string&f,const std::vector<Value>&a) {
                try {
                    auto v=call(f.find('.')==std::string::npos?p.module+"."+f:f,a);
                    if(v.type.kind!=Type::U32&&v.type.kind!=Type::Bool)fail("E_ENTRY","evaluador requiere retorno escalar para su entrada");
                    return  {
                        static_cast<uint32_t>(v.bits),output,1000000-fuel
                    };
                }
                catch(Error&e) {
                    e.output=output;
                    throw;
                }
            }
        };
    }
    std::string plainRecordProblem(const Program& p,const std::string& key) {
        std::function<std::string(const std::string&,int)> walk=[&](const std::string& k,int depth)->std::string {
            if(depth>OMNI_LIMIT_LAYOUT_DEPTH)return "struct anidado demasiado profundo para layout: "+k;
            const RecordDef* rec=nullptr; for(const auto& r:p.records)if(r.key==k)rec=&r;
            if(!rec)return "struct desconocido: "+k;
            if(!rec->generics.empty())return "un struct generico no tiene layout: "+k;
            for(const auto& f:rec->fields) {
                if(isInteger(f.type))continue;
                if(f.type.kind==Type::Record) { auto why=walk(f.type.key,depth+1); if(!why.empty())return why; continue; }
                return "el campo "+f.name+" de "+rec->name+" tiene tipo "+typeName(f.type)+": un struct plano solo contiene enteros y structs planos";
            }
            return "";
        };
        return walk(key,0);
    }
    RecordLayout recordLayout(const Program& p,const std::string& key,unsigned maxAlign) {
        const RecordDef* rec=nullptr; for(const auto& r:p.records)if(r.key==key)rec=&r;
        if(!rec)fail("E_INTERNAL","struct sin layout: "+key);
        RecordLayout out; uint64_t at=0,align=1;
        for(const auto& f:rec->fields) {
            uint64_t size=0,al=1;
            if(isInteger(f.type)) { size=integerWidth(f.type)/8; al=std::min<uint64_t>(size,maxAlign); }
            else if(f.type.kind==Type::Record) { auto sub=recordLayout(p,f.type.key,maxAlign); size=sub.size; al=sub.align; }
            else fail("E_LAYOUT","campo no plano en layout: "+f.name);
            if(rec->packed)al=1;
            const uint64_t placed=(at+al-1)/al*al;
            if(placed>at)out.padding.push_back({at,placed-at});
            out.offsets.push_back(placed); at=placed+size; align=std::max(align,al);
        }
        const uint64_t total=(at+align-1)/align*align;
        if(total>at)out.padding.push_back({at,total-at});
        if(total>4096)fail("E_LAYOUT","el layout de "+rec->name+" excede 4096 bytes");
        out.size=total; out.align=align;
        return out;
    }
    namespace {
        std::string ownershipTypeKey(const Program& p,const Type& t,const std::string& mod){
            if(!t.key.empty())return t.key;
            const auto dot=t.name.find('.');
            if(dot==std::string::npos)return mod+"."+t.name;
            const auto prefix=t.name.substr(0,dot);
            for(const auto& m:p.modules)if(m.name==mod)for(const auto& im:m.imports)
                if(im.alias==prefix)return im.target+t.name.substr(dot);
            return t.name;
        }
    }
    bool typeContainsPending(const Program& p,const Type& type,const std::string& module){
        std::map<std::string,bool> memo;std::set<std::string> active;
        std::function<bool(const Type&,const std::string&,unsigned)> visit=[&](const Type& t,const std::string& mod,unsigned depth)->bool{
            if(depth>OMNI_LIMIT_LAYOUT_DEPTH)fail("E_LIMIT","pending type graph demasiado profundo");
            if(t.kind==Type::Result)return true;
            if(t.kind==Type::Option){
                if(t.parts.size()!=1)fail("E_TYPE","Option requiere un tipo durante ownership");
                return typeContainsResource(p,t.parts[0],mod)||visit(t.parts[0],mod,depth+1);
            }
            if(t.kind!=Type::Enum&&t.kind!=Type::Record){
                for(const auto& part:t.parts)if(visit(part,mod,depth+1))return true;
                return false;
            }
            const auto key=ownershipTypeKey(p,t,mod);
            if(const auto found=memo.find(key);found!=memo.end())return found->second;
            if(!active.insert(key).second)fail("E_LAYOUT_CYCLE","ciclo de tipos durante pending: "+key);
            bool pending=false,known=false;
            for(const auto& record:p.records)if(record.module+"."+record.name==key){
                known=true;
                for(const auto& field:record.fields)if(visit(field.type,record.module,depth+1)){pending=true;break;}
                break;
            }
            if(!known)for(const auto& en:p.enums)if(en.module+"."+en.name==key){
                known=true;
                pending=typeContainsResource(p,t,mod);
                if(pending)break;
                for(const auto& variant:en.variants)if(variant.hasPayload&&visit(variant.payload,en.module,depth+1)){pending=true;break;}
                break;
            }
            if(!known)fail("E_TYPE","tipo desconocido durante pending: "+key);
            active.erase(key);memo[key]=pending;return pending;
        };
        return visit(type,module,0);
    }
    bool typeRequiresConsumption(const Program& p,const Type& type,const std::string& module){
        return type.kind==Type::Result||((type.kind==Type::Option||type.kind==Type::Enum)&&typeContainsPending(p,type,module));
    }
    bool typeContainsResource(const Program& p,const Type& type,const std::string& module) {
        std::map<std::string,bool> memo; std::set<std::string> active;
        std::function<bool(const Type&,const std::string&,unsigned)> visit=[&](const Type& t,const std::string& mod,unsigned depth)->bool {
            if(depth>OMNI_LIMIT_LAYOUT_DEPTH)fail("E_LIMIT","ownership type graph demasiado profundo");
            if(t.kind==Type::Resource)return true;
            for(const auto& part:t.parts)if(visit(part,mod,depth+1))return true;
            if(t.kind!=Type::Record&&t.kind!=Type::Enum)return false;
            const auto key=ownershipTypeKey(p,t,mod);
            if(const auto found=memo.find(key);found!=memo.end())return found->second;
            if(!active.insert(key).second)fail("E_LAYOUT_CYCLE","ciclo de tipos durante ownership: "+key);
            // Canonical metadata lookup is not name resolution or permission. The checker still verifies visibility/imports.
            bool known=false,owned=false;
            for(const auto& rec:p.records)if(rec.module+"."+rec.name==key) {
                known=true; for(const auto& field:rec.fields)if(visit(field.type,rec.module,depth+1)){owned=true;break;}
                break;
            }
            if(!known)for(const auto& en:p.enums)if(en.module+"."+en.name==key) {
                known=true; for(const auto& variant:en.variants)if(variant.hasPayload&&visit(variant.payload,en.module,depth+1)){owned=true;break;}
                break;
            }
            if(!known)fail("E_TYPE","tipo nominal desconocido durante ownership: "+key);
            active.erase(key); memo[key]=owned; return owned;
        };
        return visit(type,module,0);
    }
    uint64_t recordIdentityWord(const Program& p,const std::string& key,unsigned word) {
        if(word>3)fail("E_INTERNAL","invalid record identity word");
        if(const auto why=plainRecordProblem(p,key);!why.empty())fail("E_LAYOUT",why);
        std::string description="omni.plain-record.identity/1";
        auto add=[&](const std::string& value){ description+=std::to_string(value.size())+":"+value; };
        std::function<void(const std::string&)> visitRecord=[&](const std::string& k){
            const RecordDef* rec=nullptr;
            for(const auto& candidate:p.records)if(candidate.key==k)rec=&candidate;
            if(!rec)fail("E_INTERNAL","missing record identity definition");
            add(k); add(rec->packed?"packed":"native"); add(std::to_string(rec->fields.size()));
            for(const auto& field:rec->fields){
                add(field.name);
                if(field.type.kind==Type::Record){ add("record"); visitRecord(field.type.key); }
                else add(typeName(field.type));
            }
        };
        visitRecord(key);
        return std::stoull(sha256(description).substr(word*16u,16u),nullptr,16);
    }
    ThreadLocalLayout threadLocalLayout(const Program& p) {
        ThreadLocalLayout out; uint64_t at=16;
        for(const auto* d:orderedThreadLocals(p)) {
            const uint64_t w=integerWidth(d->type)/8;
            at=(at+w-1)/w*w; out.offsets.push_back(at); at+=w;
        }
        out.size=(at+15)/16*16;
        if(out.size>4096)fail("E_THREAD_LOCAL","el bloque thread_local excede 4096 bytes");
        return out;
    }
    namespace { TargetFacts activeTargetFacts; }
    void setTargetFacts(const TargetFacts& facts) { activeTargetFacts=facts; }
    const TargetFacts& targetFacts() { return activeTargetFacts; }
    void validate(Program&p) {
        if(!p.authoringSource.empty()) {
            const auto source=p.authoringSource; const auto paths=p.sources;
            p=parseParticleProgram(source); p.authoringSource=source; p.sources=paths;
        } else if(!p.genericTemplates.empty()||!p.genericRecordTemplates.empty()||!p.genericEnumTemplates.empty()||!p.traitImpls.empty()) {
            p.authoringSource=particle(p);
        }
        auto canonicalizeCaps=[](Function& f){
            std::set<std::string> canonical;
            for(auto&c:f.capabilities){ auto x=canonicalCapability(c); if(!isKnownCapability(x))fail("E_CAPABILITY","capability desconocida: "+c,f.loc); canonical.insert(x); }
            f.capabilities=std::move(canonical);
        };
        // Generic declarations are source-level code and must fail closed on invalid authority metadata even if never instantiated.
        for(auto& f:p.genericTemplates) canonicalizeCaps(f);
        // A static assertion is checked as the pure function it is, so it lives among the functions while the program is validated and goes back to its own list afterwards.
        for(auto& f:p.staticAsserts) p.functions.push_back(std::move(f));
        p.staticAsserts.clear();
        lowerTry(p);
        expandGenerics(p);
        for(auto& f:p.functions) canonicalizeCaps(f);
        Checker(p).run();
        // Static assertions are decided here, by the evaluator, over the program that has just been checked; they leave no trace in the program (they are a property of the source).
        // A scalar constant defined by an expression is decided now: if it cannot be evaluated (overflow, division by zero, a cycle between constants, running out of steps) the program is refused.
        for(const auto& f:p.functions) {
            if(!f.isConst||f.body.size()!=1)continue;
            const Expr& init=f.body[0].expr;
            if(init.kind==Expr::Number||init.kind==Expr::Boolean||(init.kind==Expr::Unary&&init.text=="-"&&init.args.size()==1&&init.args[0].kind==Expr::Number)||(init.kind==Expr::Call&&init.text=="array"))continue;
            try { (void)evaluateValue(p,f.module+"."+f.name); }
            catch(const Error& e) { fail("E_CONST","la constante no se pudo evaluar en compilación ("+e.code+"): "+f.name,f.loc); }
        }
        for(const auto& f:p.functions) {
            if(!f.isStaticAssert)continue;
            uint32_t holds=0;
            try { holds=evaluate(p,f.module+"."+f.name).result; }
            catch(const Error& e) { fail("E_STATIC_ASSERT","la aserción no se pudo evaluar en compilación ("+e.code+"): "+f.assertMessage,f.loc); }
            if(!holds)fail("E_STATIC_ASSERT",f.assertMessage,f.loc);
        }
        for(auto& f:p.functions) if(f.isStaticAssert) p.staticAsserts.push_back(f);
        p.functions.erase(std::remove_if(p.functions.begin(),p.functions.end(),[](const Function& f){ return f.isStaticAssert; }),p.functions.end());
    }
    void requireMain(const Program&p) {
        for(auto&f:p.functions)if(f.module==p.module&&f.name=="main") {
            if(!f.params.empty()||f.result!=Type::U32)fail("E_ENTRY","main debe ser () u32");
            return;
        }
        fail("E_ENTRY","se requiere main en modulo de entrada");
    }
    Value evaluateValue(const Program&p,const std::string& key) {
        return Evaluator(p,nullptr).value(key);
    }
    EvalResult evaluate(const Program&p,const std::string&f,const std::vector<Value>&a,const HostPolicy* hostPolicy) {
        return Evaluator(p,hostPolicy).run(f,a);
    }
}

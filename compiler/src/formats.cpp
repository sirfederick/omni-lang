#include "omni.hpp"
namespace omni  {
    namespace  {
        struct S  {
            bool list=false,quoted=false;
            std::string a;
            std::vector<S> children;
            Loc loc;
        };
        class SParser  {
            const std::string& s;
            size_t p=0,line=1,col=1,nodes=0;
            char take()  {
                char c=s[p++];
                if(c=='\n')  {
                    line++;
                    col=1;
                }
                else col++;
                return c;
            }
            void ws()  {
                while(p<s.size()&&std::isspace(static_cast<unsigned char>(s[p])))take();
            }
            S one(int d)  {
                ws();
                if(d>128)fail("E_LIMIT","Wave demasiado profundo/grande");
                if((++nodes&1023u)==0u)budgetCheck("el lector Wave");
                if(p==s.size())fail("E_WAVE","Wave truncado");
                S x;
                x.loc=  {
                    line,col
                };
                char c=take();
                if(c=='(')  {
                    x.list=true;
                    ws();
                    while(p<s.size()&&s[p]!=')')  {
                        x.children.push_back(one(d+1));
                        ws();
                    }
                    if(p==s.size())fail("E_WAVE","lista sin cierre",x.loc);
                    take();
                }
                else if(c=='"')  {
                    x.quoted=true;
                    bool closed=false;
                    while(p<s.size())  {
                        char z=take();
                        if(z=='"')  {
                            closed=true;
                            break;
                        }
                        if(z=='\n'||z=='\r')fail("E_WAVE","salto de linea no escapado",x.loc);
                        if(z=='\\')  {
                            if(p==s.size())fail("E_WAVE","escape truncado",x.loc);
                            z=take();
                            switch(z)  {
                                case 'n':z='\n';
                                break;
                                case 'r':z='\r';
                                break;
                                case 't':z='\t';
                                break;
                                case '"':case '\\':break;
                                default:fail("E_WAVE","escape invalido",x.loc);
                            }
                        }
                        x.a+=z;
                        if(x.a.size()>4096)fail("E_LIMIT","cadena Wave demasiado grande",x.loc);
                    }
                    if(!closed)fail("E_WAVE","cadena sin cierre",x.loc);
                }
                else  {
                    if(c==')')fail("E_WAVE","cierre inesperado",x.loc);
                    x.a+=c;
                    while(p<s.size()&&!std::isspace(static_cast<unsigned char>(s[p]))&&s[p]!='('&&s[p]!=')')x.a+=take();
                    if(x.a.size()>128)fail("E_LIMIT","atomo Wave demasiado grande",x.loc);
                }
                return x;
            }
            public:explicit SParser(const std::string& x):s(x)  {
            }
            S run()  {
                auto x=one(0);
                ws();
                if(p!=s.size())fail("E_WAVE","contenido adicional",  {
                    line,col
                });
                return x;
            }
        };
        const std::string& atom(const S& x,bool quoted=false)  {
            if(x.list||x.quoted!=quoted)fail("E_WAVE",quoted?"se esperaba cadena":"se esperaba atomo",x.loc);
            return x.a;
        }
        void form(const S& x,const std::string& tag,size_t n)  {
            if(!x.list||x.children.size()!=n||atom(x.children[0])!=tag)fail("E_WAVE","forma invalida: "+tag,x.loc);
        }
        std::string tag(const S& x)  {
            if(!x.list||x.children.empty())fail("E_WAVE","se esperaba lista no vacia",x.loc);
            return atom(x.children[0]);
        }
        uint64_t number64(const S& x)  {
            uint64_t n=0;
            auto s=atom(x);
            if(s.empty())fail("E_WAVE","numero vacio",x.loc);
            for(char c:s)  {
                if(c<'0'||c>'9')fail("E_WAVE","entero decimal esperado",x.loc);
                const auto d=uint64_t(c-'0');
                if(n>(UINT64_MAX-d)/10)fail("E_OVERFLOW_LITERAL","entero fuera de u64",x.loc);
                n=n*10+d;
            }
            return n;
        }
        void wb(std::ostringstream&,const std::vector<Stmt>&,int);
        std::vector<Stmt> rb(const S&,int);
        std::string we(const Expr&e) {
            switch(e.kind) {
                case Expr::Number:return "("+typeName(e.type.kind==Type::Unknown?e.annotation:e.type)+" "+std::to_string(e.value)+")";
                case Expr::Boolean:return e.value?"(bool true)":"(bool false)";
                case Expr::Text:return "(text-value "+quote(e.text)+")";
                case Expr::Ref:return "(ref "+e.text+")";
                case Expr::Join:return "(join "+e.text+")";
                case Expr::Cancel:return "(cancel "+e.text+")";
                case Expr::Deadline:return "(deadline "+e.text+" "+we(e.args.at(0))+")";
                case Expr::Channel:return "(channel "+typeName(e.annotation)+" "+we(e.args.at(0))+")";
                case Expr::Send:return "(send "+e.text+" "+we(e.args.at(0))+")";
                case Expr::Receive:return "(receive "+e.text+")";
                case Expr::Try:fail("E_INTERNAL","? sin bajar antes de serializar",e.loc);
                case Expr::Close:return "(close "+e.text+")";
                case Expr::Call: {
                    std::string s="(call "+(e.genericTarget.empty()?e.text:e.genericTarget);
                    for(auto&a:e.args)s+=" "+we(a);
                    return s+")";
                }
                case Expr::Unary:return "(unary "+quote(e.text)+" "+we(e.args[0])+")";
                case Expr::Binary:return "(binary "+quote(e.text)+" "+we(e.args[0])+" "+we(e.args[1])+")";
                case Expr::RecordInit: {
                    std::string s="(record "+e.text;
                    for(size_t i=0; i<e.args.size(); i++)s+=" ("+e.names[i]+" "+we(e.args[i])+")";
                    return s+")";
                }
                case Expr::Variant: { std::string s="(variant "+e.text; if(!e.args.empty())s+=" "+we(e.args[0]); return s+")"; }
                case Expr::Field:return "(field "+we(e.args[0])+" "+e.text+")";
                case Expr::Ok:case Expr::Err:return std::string(e.kind==Expr::Ok?"(ok ":"(err ")+typeName(e.annotation)+" "+we(e.args[0])+")";
                case Expr::Some:return "(some "+typeName(e.annotation)+" "+we(e.args[0])+")";
                case Expr::None:return "(none "+typeName(e.annotation)+")";
                case Expr::ClosureCall: {
                    if(!e.closureBody)fail("E_WAVE","closure sin cuerpo",e.loc);
                    std::ostringstream b; wb(b,*e.closureBody,1);
                    std::string s="(closure-call (params";
                    for(const auto& p:e.closureParams)s+=" ("+p.name+" "+typeName(p.type)+")";
                    s+=") (result "+typeName(e.annotation)+") (captures";
                    for(const auto& c:e.closureCaptures)s+=" "+c;
                    s+=") "+b.str()+" (args";
                    for(const auto& a:e.args)s+=" "+we(a);
                    return s+"))";
                }
            }
            fail("E_INTERNAL","expr sin Wave");
        }
        void wb(std::ostringstream&o,const std::vector<Stmt>&b,int n) {
            std::string ind(static_cast<size_t>(n)*2u,' ');
            o<<"(block";
            for(auto&s:b) {
                o<<"\n"<<ind<<"  ";
                switch(s.kind) {
                    case Stmt::Let:case Stmt::Var:o<<"("<<(s.kind==Stmt::Let?"let":"var")<<" "<<s.name<<" "<<typeName(s.declared)<<" "<<we(s.expr)<<")";
                    break;
                    case Stmt::Assign:o<<"(set "<<s.name<<" "<<we(s.expr)<<")";
                    break;
                    case Stmt::Return:o<<"(return "<<we(s.expr)<<")";
                    break;
                    case Stmt::TaskScope:o<<"(task-scope "; wb(o,s.body,n+1); o<<")"; break;
                    case Stmt::Spawn:o<<"(spawn "<<s.name<<" "<<we(s.expr)<<")"; break;
                    case Stmt::Print:o<<"(print "<<we(s.expr)<<")";
                    break;
                    case Stmt::PrintText:o<<"(text "<<quote(s.text)<<")";
                    break;
                    case Stmt::If:o<<"(if "<<we(s.expr)<<" ";
                    wb(o,s.body,n+1);
                    o<<" ";
                    wb(o,s.other,n+1);
                    o<<")";
                    break;
                    case Stmt::Loop:o<<"(for "<<we(s.expr)<<" ";
                    wb(o,s.body,n+1);
                    o<<")";
                    break;
                    case Stmt::ForEach:o<<"(for-each "<<s.name<<" "<<we(s.expr)<<" ";
                    wb(o,s.body,n+1); o<<")"; break;
                    case Stmt::Destructure: {
                        o<<"(let-tuple (";
                        for(size_t ni=0;ni<s.names.size();++ni){ if(ni)o<<" "; o<<s.names[ni]; }
                        o<<") "<<we(s.expr)<<")"; break;
                    }
                    case Stmt::Break:o<<"(break)"; break;
                    case Stmt::Continue:o<<"(continue)"; break;
                    case Stmt::Match:o<<"(match "<<we(s.expr)<<" (ok "<<s.name<<" ";
                    wb(o,s.body,n+1);
                    o<<") (err "<<s.otherName<<" ";
                    wb(o,s.other,n+1);
                    o<<"))";
                    break;
                    case Stmt::MatchOption:o<<"(match-option "<<we(s.expr)<<" (some "<<s.name<<" ";
                    wb(o,s.body,n+1);
                    o<<") (none "; wb(o,s.other,n+1); o<<"))"; break;
                    case Stmt::MatchEnum: {
                        o<<"(match-enum "<<we(s.expr);
                        for(size_t ai=0;ai<s.arms.size();++ai){ o<<" (case "<<s.armVariants[ai]; if(!s.armNames[ai].empty())o<<" "<<s.armNames[ai]; o<<" "; wb(o,s.arms[ai],n+1); o<<")"; }
                        o<<")"; break;
                    }
                }
            }
            o<<")";
        }
        Expr re(const S&x,int d) {
            if(d>OMNI_LIMIT_EXPR_HEIGHT)fail("E_LIMIT","expresion Wave demasiado profunda",x.loc);
            auto k=tag(x);
            Expr e;
            e.loc=x.loc;
            if(k=="u8"||k=="u16"||k=="u32"||k=="u64"||k=="i8"||k=="i16"||k=="i32"||k=="i64"||k=="f32"||k=="f64") {
                form(x,k,2);
                e.kind=Expr::Number;
                e.annotation=parseType(k,x.loc);
                e.value=number64(x.children[1]);
            }
            else if(k=="bool") {
                form(x,k,2);
                e.kind=Expr::Boolean;
                auto a=atom(x.children[1]);
                if(a!="true"&&a!="false")fail("E_WAVE","bool invalido",x.loc);
                e.value=a=="true";
            }
            else if(k=="text-value") {
                form(x,k,2);
                e.kind=Expr::Text;
                e.text=atom(x.children[1],true);
            }
            else if(k=="ref") {
                form(x,k,2);
                e.kind=Expr::Ref;
                e.text=atom(x.children[1]);
            }
            else if(k=="join") { form(x,k,2); e.kind=Expr::Join; e.text=atom(x.children[1]); }
            else if(k=="cancel") { form(x,k,2); e.kind=Expr::Cancel; e.text=atom(x.children[1]); }
            else if(k=="deadline") { form(x,k,3); e.kind=Expr::Deadline; e.text=atom(x.children[1]); e.args.push_back(re(x.children[2],d+1)); }
            else if(k=="channel") { form(x,k,3); e.kind=Expr::Channel; e.annotation=parseType(atom(x.children[1]),x.loc); e.args.push_back(re(x.children[2],d+1)); }
            else if(k=="send") { form(x,k,3); e.kind=Expr::Send; e.text=atom(x.children[1]); e.args.push_back(re(x.children[2],d+1)); }
            else if(k=="receive") { form(x,k,2); e.kind=Expr::Receive; e.text=atom(x.children[1]); }
            else if(k=="close") { form(x,k,2); e.kind=Expr::Close; e.text=atom(x.children[1]); }
            else if(k=="call") {
                if(x.children.size()<2)fail("E_WAVE","call invalido",x.loc);
                e.kind=Expr::Call;
                e.text=atom(x.children[1]);
                for(size_t i=2; i<x.children.size(); i++)e.args.push_back(re(x.children[i],d+1));
            }
            else if(k=="unary"||k=="binary") {
                form(x,k,k=="unary"?3:4);
                e.kind=k=="unary"?Expr::Unary:Expr::Binary;
                e.text=atom(x.children[1],true);
                for(size_t i=2; i<x.children.size(); i++)e.args.push_back(re(x.children[i],d+1));
            }
            else if(k=="record") {
                if(x.children.size()<3)fail("E_WAVE","record invalido",x.loc);
                e.kind=Expr::RecordInit;
                e.text=atom(x.children[1]);
                for(size_t i=2; i<x.children.size(); i++) {
                    auto&f=x.children[i];
                    if(!f.list||f.children.size()!=2)fail("E_WAVE","campo invalido",f.loc);
                    e.names.push_back(atom(f.children[0]));
                    e.args.push_back(re(f.children[1],d+1));
                }
            }
            else if(k=="variant") {
                if(x.children.size()!=2&&x.children.size()!=3)fail("E_WAVE","variant invalido",x.loc);
                e.kind=Expr::Variant; e.text=atom(x.children[1]); if(x.children.size()==3)e.args.push_back(re(x.children[2],d+1));
            }
            else if(k=="field") {
                form(x,k,3);
                e.kind=Expr::Field;
                e.args.push_back(re(x.children[1],d+1));
                e.text=atom(x.children[2]);
            }
            else if(k=="ok"||k=="err") {
                form(x,k,3);
                e.kind=k=="ok"?Expr::Ok:Expr::Err;
                e.annotation=parseType(atom(x.children[1]),x.loc);
                e.args.push_back(re(x.children[2],d+1));
            }
            else if(k=="some") { form(x,k,3); e.kind=Expr::Some; e.annotation=parseType(atom(x.children[1]),x.loc); e.args.push_back(re(x.children[2],d+1)); }
            else if(k=="none") { form(x,k,2); e.kind=Expr::None; e.annotation=parseType(atom(x.children[1]),x.loc); }
            else if(k=="closure-call") {
                form(x,k,6); e.kind=Expr::ClosureCall;
                const auto& ps=x.children[1];
                if(tag(ps)!="params")fail("E_WAVE","parametros de closure invalidos",ps.loc);
                for(size_t i=1;i<ps.children.size();++i){ const auto& p=ps.children[i]; if(!p.list||p.children.size()!=2)fail("E_WAVE","parametro de closure invalido",p.loc); e.closureParams.push_back({atom(p.children[0]),parseType(atom(p.children[1]),p.loc),-1,p.loc,""}); }
                form(x.children[2],"result",2); e.annotation=parseType(atom(x.children[2].children[1]),x.children[2].loc);
                const auto& cs=x.children[3]; if(tag(cs)!="captures")fail("E_WAVE","capturas de closure invalidas",cs.loc);
                for(size_t i=1;i<cs.children.size();++i)e.closureCaptures.push_back(atom(cs.children[i]));
                e.closureBody=std::make_shared<std::vector<Stmt>>(rb(x.children[4],d+1));
                const auto& as=x.children[5]; if(tag(as)!="args")fail("E_WAVE","argumentos de closure invalidos",as.loc);
                for(size_t i=1;i<as.children.size();++i)e.args.push_back(re(as.children[i],d+1));
            }
            else fail("E_WAVE","operacion desconocida: "+k,x.loc);
            return e;
        }
        std::vector<Stmt> rb(const S&x,int d) {
            if(d>OMNI_LIMIT_BLOCK_DEPTH)fail("E_LIMIT","bloques Wave demasiado profundos",x.loc);
            if(tag(x)!="block")fail("E_WAVE","block requerido",x.loc);
            std::vector<Stmt>b;
            for(size_t i=1; i<x.children.size(); i++) {
                auto&y=x.children[i];
                auto k=tag(y);
                Stmt s;
                s.loc=y.loc;
                if(k=="let"||k=="var") {
                    form(y,k,4);
                    s.kind=k=="let"?Stmt::Let:Stmt::Var;
                    s.name=atom(y.children[1]);
                    auto ty=atom(y.children[2]);
                    s.declared=ty=="infer"?Type(Type::Unknown):parseType(ty,y.loc);
                    s.expr=re(y.children[3],1);
                }
                else if(k=="set") {
                    form(y,k,3);
                    s.kind=Stmt::Assign;
                    s.name=atom(y.children[1]);
                    s.expr=re(y.children[2],1);
                }
                else if(k=="return"||k=="print") {
                    form(y,k,2);
                    s.kind=k=="return"?Stmt::Return:Stmt::Print;
                    s.expr=re(y.children[1],1);
                }
                else if(k=="task-scope") { form(y,k,2); s.kind=Stmt::TaskScope; s.body=rb(y.children[1],d+1); }
                else if(k=="spawn") { form(y,k,3); s.kind=Stmt::Spawn; s.name=atom(y.children[1]); s.expr=re(y.children[2],d+1); }
                else if(k=="text") {
                    form(y,k,2);
                    s.kind=Stmt::PrintText;
                    s.text=atom(y.children[1],true);
                }
                else if(k=="if") {
                    form(y,k,4);
                    s.kind=Stmt::If;
                    s.expr=re(y.children[1],1);
                    s.body=rb(y.children[2],d+1);
                    s.other=rb(y.children[3],d+1);
                }
                else if(k=="for") {
                    form(y,k,3);
                    s.kind=Stmt::Loop;
                    s.expr=re(y.children[1],1);
                    s.body=rb(y.children[2],d+1);
                }
                else if(k=="for-each") {
                    form(y,k,4); s.kind=Stmt::ForEach; s.name=atom(y.children[1]);
                    s.expr=re(y.children[2],1); s.body=rb(y.children[3],d+1);
                }
                else if(k=="let-tuple") {
                    form(y,k,3); s.kind=Stmt::Destructure;
                    const auto& ns=y.children[1];
                    if(!ns.list||ns.children.empty())fail("E_WAVE","let-tuple requiere bindings",ns.loc);
                    for(const auto& item:ns.children){ auto n=atom(item); if(!validIdentifier(n))fail("E_WAVE","binding let-tuple invalido",item.loc); s.names.push_back(n); }
                    s.expr=re(y.children[2],1);
                }
                else if(k=="break") { form(y,k,1); s.kind=Stmt::Break; }
                else if(k=="continue") { form(y,k,1); s.kind=Stmt::Continue; }
                else if(k=="match") {
                    form(y,k,4);
                    s.kind=Stmt::Match;
                    s.expr=re(y.children[1],1);
                    form(y.children[2],"ok",3);
                    form(y.children[3],"err",3);
                    s.name=atom(y.children[2].children[1]);
                    s.body=rb(y.children[2].children[2],d+1);
                    s.otherName=atom(y.children[3].children[1]);
                    s.other=rb(y.children[3].children[2],d+1);
                }
                else if(k=="match-option") {
                    form(y,k,4); s.kind=Stmt::MatchOption; s.expr=re(y.children[1],1);
                    form(y.children[2],"some",3); form(y.children[3],"none",2);
                    s.name=atom(y.children[2].children[1]); s.body=rb(y.children[2].children[2],d+1);
                    s.other=rb(y.children[3].children[1],d+1);
                }
                else if(k=="match-enum") {
                    if(y.children.size()<3)fail("E_WAVE","match-enum invalido",y.loc);
                    s.kind=Stmt::MatchEnum; s.expr=re(y.children[1],1);
                    for(size_t ci=2;ci<y.children.size();++ci){
                        auto &c=y.children[ci]; if(!c.list||(c.children.size()!=3&&c.children.size()!=4)||atom(c.children[0])!="case")fail("E_WAVE","case enum invalido",c.loc);
                        s.armVariants.push_back(atom(c.children[1])); size_t bi=2; std::string bind; if(c.children.size()==4)bind=atom(c.children[bi++]);
                        s.armNames.push_back(bind); s.arms.push_back(rb(c.children[bi],d+1)); s.armBindings.push_back(-1); s.armVariantIndices.push_back(-1); s.armPayloadFields.push_back(-1);
                    }
                }
                else fail("E_WAVE","instruccion desconocida: "+k,y.loc);
                b.push_back(std::move(s));
            }
            return b;
        }
        bool a85Expr(const Expr& e) {
            if(e.kind==Expr::Join||e.kind==Expr::Cancel||e.kind==Expr::Deadline||e.kind==Expr::Channel||e.kind==Expr::Send||e.kind==Expr::Receive||e.kind==Expr::Close)return true;
            for(const auto& a:e.args)if(a85Expr(a))return true;
            if(e.closureBody)for(const auto& s:*e.closureBody)if(a85Expr(s.expr))return true;
            return false;
        }
        bool a85Block(const std::vector<Stmt>& b) {
            for(const auto& s:b) {
                if(s.kind==Stmt::TaskScope||s.kind==Stmt::Spawn||a85Expr(s.expr))return true;
                if(a85Block(s.body)||a85Block(s.other))return true;
                for(const auto& arm:s.arms)if(a85Block(arm))return true;
            }
            return false;
        }
        bool a85Program(const Program& p) {
            for(const auto& f:p.functions)if(a85Block(f.body))return true;
            return false;
        }
        bool a86Block(const std::vector<Stmt>& b);
        bool a86Expr(const Expr& e) {
            if(e.kind==Expr::Call&&(e.text=="host.read"||e.text=="host.write"||
               e.text=="host.process"||e.text=="host.tcp"||e.text=="host.ffi"))return true;
            for(const auto& a:e.args)if(a86Expr(a))return true;
            if(e.closureBody&&a86Block(*e.closureBody))return true;
            return false;
        }
        bool a86Block(const std::vector<Stmt>& b) {
            for(const auto& s:b) {
                if(a86Expr(s.expr)||a86Block(s.body)||a86Block(s.other))return true;
                for(const auto& arm:s.arms)if(a86Block(arm))return true;
            }
            return false;
        }
        bool a86Program(const Program& p) {
            for(const auto& f:p.functions)if(a86Block(f.body))return true;
            return false;
        }
        // CP-02a: a function with a Borrow/BorrowMut result is only representable from Wave21/OMC21.
        bool borrowReturnFunction(const Function& f) { return f.result.kind==Type::Borrow||f.result.kind==Type::BorrowMut; }
        // CP-07: declarative bit intrinsics (BIT_INTRINSICS_CANDIDATE.md) share the Wave21/OMC21 fence.
        bool bitIntrinsicName(const std::string& n) {
            return n=="bit.and"||n=="bit.or"||n=="bit.xor"||n=="bit.not"||n=="bit.shl"||n=="bit.shr";
        }
        // CP-01: owning Options and nested pending sums share Wave21/OMC21.
        // The compatibility projection retains the exact historical selection.
        bool pendingCompositionType(const Program& p,const Type& t,const std::string& module,bool recursiveOptions) {
            if(t.kind==Type::Option&&t.parts.size()==1&&
               (t.parts[0].kind==Type::Resource||(recursiveOptions&&
                (typeContainsResource(p,t.parts[0],module)||typeContainsPending(p,t.parts[0],module)))))return true;
            if(recursiveOptions&&t.kind==Type::Result)
                for(const auto& payload:t.parts)if(typeRequiresConsumption(p,payload,module))return true;
            for(const auto& q:t.parts)if(pendingCompositionType(p,q,module,recursiveOptions))return true;
            return false;
        }
        // CP-08/09/13 (G5, hardware representation fence): machine primitives (raw./port./cpu./atomic./tls./pcpu.), the nominal-resource builtins and
        // the capabilities that authorize them are new semantics too. They need no new grammar, but a reader of <= 20 would reject them only
        // incidentally ("unknown Wire capability"); they share the Wave21/OMC21 fence so that the rejection is E_VERSION and the artifact
        // never carries an old version label over new semantics. See spec/HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md.
        bool hardwareIntrinsicName(const std::string& n) {
            return n.rfind("raw.",0)==0||n.rfind("simd.",0)==0||n.rfind("port.",0)==0||n.rfind("cpu.",0)==0||n.rfind("atomic.",0)==0||n.rfind("layout.",0)==0||n.rfind("tls.",0)==0||n.rfind("pcpu.",0)==0||
                   n=="resource.seal"||n=="resource.unseal"||n=="resource.peek"||n=="resource.inner"||n=="resource.inner_mut"||
                   n=="buffer.grow"||n=="buffer.zero"||   // CP-04: dynamic storage primitives (spec/DYNAMIC_STORAGE_CANDIDATE.md)
                   n.rfind("slots.",0)==0;                // CP-01/CP-04: owned slots (spec/OWNED_SLOTS_CANDIDATE.md)
        }
        bool hardwareCapability(const std::string& c) {
            return c=="memory.raw"||c=="memory.atomic"||c=="memory.tls"||c=="memory.pcpu"||c=="port.io"||c=="cpu.control"||c=="cpu.syscall";
        }
        bool nominalResourceType(const Type& t) {
            if(t.kind==Type::Resource&&t.name!="Buffer")return true;
            for(const auto& q:t.parts)if(nominalResourceType(q))return true;
            return false;
        }
        bool ownedTupleType(const Program& p,const Type& t,const std::string& module){
            if((t.kind==Type::Tuple||t.kind==Type::Array)&&(typeContainsResource(p,t,module)||typeContainsPending(p,t,module)))return true;
            for(const auto& part:t.parts)if(ownedTupleType(p,part,module))return true;
            return false;
        }
        bool a87Block(const Program& p,const std::vector<Stmt>& b,const std::string& module,bool recursiveOptions);
        bool a87Expr(const Program& p,const Expr& e,const std::string& module,bool recursiveOptions) {
            if(e.kind==Expr::Call&&(bitIntrinsicName(e.text)||hardwareIntrinsicName(e.text)))return true;
            if(pendingCompositionType(p,e.annotation,module,recursiveOptions)||nominalResourceType(e.annotation))return true;
            for(const auto& a:e.args)if(a87Expr(p,a,module,recursiveOptions))return true;
            if(e.closureBody&&a87Block(p,*e.closureBody,module,recursiveOptions))return true;
            return false;
        }
        bool a87Block(const Program& p,const std::vector<Stmt>& b,const std::string& module,bool recursiveOptions) {
            for(const auto& s:b) {
                if(a87Expr(p,s.expr,module,recursiveOptions)||pendingCompositionType(p,s.declared,module,recursiveOptions)||nominalResourceType(s.declared)||a87Block(p,s.body,module,recursiveOptions)||a87Block(p,s.other,module,recursiveOptions))return true;
                for(const auto& arm:s.arms)if(a87Block(p,arm,module,recursiveOptions))return true;
            }
            return false;
        }
        bool a87Function(const Program& p,const Function& f,bool recursiveOptions=true) {
            if(recursiveOptions&&f.requiresOwnedTupleFence)return true;
            if(borrowReturnFunction(f)||pendingCompositionType(p,f.result,f.module,recursiveOptions)||nominalResourceType(f.result)||a87Block(p,f.body,f.module,recursiveOptions))return true;
            for(const auto& a:f.params)if(pendingCompositionType(p,a.type,f.module,recursiveOptions)||nominalResourceType(a.type))return true;
            for(const auto& c:f.capabilities)if(hardwareCapability(c))return true;
            return false;
        }
        bool a87Program(const Program& p,bool recursiveOptions) {
            if(!p.threadLocals.empty())return true;   // CP-11: the thread_local item is new semantics
            for(const auto& f:p.functions)if(f.linkage())return true;   // CP-07: export / extern / section / noinline are new semantics
            for(const auto& r:p.records){
                if(r.packed||r.opaque||r.externC)return true;   // CP-07: packed layout, opaque and extern records are new semantics
                // The ONME2 compatibility projection retains its original fence.
                for(const auto& field:r.fields)if(recursiveOptions&&
                    (nominalResourceType(field.type)||typeContainsPending(p,field.type,r.module)||ownedTupleType(p,field.type,r.module)))return true;
            }
            for(const auto& en:p.enums)for(const auto& v:en.variants)
                if(v.hasPayload&&(typeContainsResource(p,v.payload,en.module)||(recursiveOptions&&typeContainsPending(p,v.payload,en.module))))return true;
            for(const auto& f:p.functions)if(a87Function(p,f,recursiveOptions))return true;
            return false;
        }
        uint32_t emittedRepresentation(const Program& p,bool recursiveOptions=true) {
            return a87Program(p,recursiveOptions)?21u:(a86Program(p)?20u:(a85Program(p)?19u:18u));
        }
        bool visibility(const S&x) {
            form(x,"visibility",2);
            auto v=atom(x.children[1]);
            if(v!="public"&&v!="private")fail("E_WAVE","visibilidad invalida",x.loc);
            return v=="public";
        }
        Function rf(const S&y,const std::string&mod,bool old) {
            const bool linked=!old&&y.list&&y.children.size()>3&&y.children[3].list&&!y.children[3].children.empty()&&atom(y.children[3].children[0])=="linkage";
            form(y,"func",old?6:(linked?8:7));
            Function f;
            f.loc=y.loc;
            f.name=atom(y.children[1]);
            f.module=mod;
            size_t i=2;
            if(!old)f.pub=visibility(y.children[i++]);
            if(linked) {
                const auto& l=y.children[i++];
                bool sawExport=false,sawExtern=false,sawSection=false,sawNoInline=false;
                for(size_t k=1;k<l.children.size();++k) {
                    const auto mark=tag(l.children[k]);
                    if(mark=="export"&&!sawExport&&l.children[k].children.size()==2) { sawExport=true; f.exportName=atom(l.children[k].children[1],true); }
                    else if(mark=="extern"&&!sawExtern&&l.children[k].children.size()==2) { sawExtern=true; f.externName=atom(l.children[k].children[1],true); f.isExtern=true; }
                    else if(mark=="section"&&!sawSection&&l.children[k].children.size()==2) { sawSection=true; f.section=atom(l.children[k].children[1],true); }
                    else if(mark=="noinline"&&!sawNoInline&&l.children[k].children.size()==1) { sawNoInline=true; f.noInline=true; }
                    else fail("E_WAVE","marca de enlace invalida",l.loc);
                }
                if(l.children.size()<2)fail("E_WAVE","linkage vacio",l.loc);
            }
            auto&pars=y.children[i++];
            if(tag(pars)!="params")fail("E_WAVE","params requerido");
            for(size_t j=1; j<pars.children.size(); j++) {
                auto&a=pars.children[j];
                if(!a.list||(a.children.size()!=2&&a.children.size()!=3))fail("E_WAVE","parametro invalido",a.loc);
                Param p; size_t pi=0;
                if(a.children.size()==3)p.receiverMode=atom(a.children[pi++]);
                p.name=atom(a.children[pi++]); p.type=parseType(atom(a.children[pi]),a.loc); p.loc=a.loc;
                f.params.push_back(std::move(p));
            }
            form(y.children[i],"result",2);
            f.result=parseType(atom(y.children[i].children[1]),y.loc);
            i++;
            auto& ef=y.children[i++];
            if(tag(ef)!="effects"||ef.children.size()<2)fail("E_WAVE","effects invalido",ef.loc);
            for(size_t ei=1;ei<ef.children.size();++ei){
                auto effect=atom(ef.children[ei]);
                if(effect=="pure") { if(ef.children.size()!=2) fail("E_CAPABILITY","pure no se mezcla con capabilities",ef.loc); continue; }
                if(effect=="io") { auto xs=legacyIoCapabilities(); f.capabilities.insert(xs.begin(),xs.end()); continue; }
                auto cap=canonicalCapability(effect);
                if(!isKnownCapability(cap))fail("E_CAPABILITY","capability Wave desconocida: "+effect,ef.loc);
                f.capabilities.insert(cap);
            }
            f.body=rb(y.children[i],1);
            return f;
        }
        class Writer  {
            public: std::vector<uint8_t>v;
            void byte(uint8_t b) {
                v.push_back(b);
            }
            void u32(uint32_t n) {
                for(int i=0; i<4; i++)byte(static_cast<uint8_t>(n>>(8*i)));
            }
            void u64(uint64_t n) { for(int i=0;i<8;i++)byte(static_cast<uint8_t>(n>>(8*i))); }
            void countSize(size_t n) { if(n>UINT32_MAX)fail("E_LIMIT","conteo Wire excede u32"); u32(static_cast<uint32_t>(n)); }
            void str(const std::string&s) {
                countSize(s.size());
                v.insert(v.end(),s.begin(),s.end());
            }
            void ty(const Type&t) {
                str(typeName(t));
            }
            void ex(const Expr&e) {
                byte(e.kind);
                switch(e.kind) {
                    case Expr::Number:ty(e.type.kind==Type::Unknown?e.annotation:e.type); u64(e.value); break;
                    case Expr::Boolean:u32(static_cast<uint32_t>(e.value)); break;
                    case Expr::Text:str(e.text);
                    break;
                    case Expr::Ref:str(e.text);
                    break;
                    case Expr::Join:str(e.text); break;
                    case Expr::Cancel:str(e.text); break;
                    case Expr::Deadline:str(e.text); ex(e.args.at(0)); break;
                    case Expr::Channel:ty(e.annotation); ex(e.args.at(0)); break;
                    case Expr::Send:str(e.text); ex(e.args.at(0)); break;
                    case Expr::Try:fail("E_INTERNAL","? sin bajar antes de serializar",e.loc);
                    case Expr::Receive:case Expr::Close:str(e.text); break;
                    case Expr::Call:case Expr::Unary:case Expr::Binary:str(e.kind==Expr::Call&&!e.genericTarget.empty()?e.genericTarget:e.text);
                    countSize(e.args.size());
                    for(auto&a:e.args)ex(a);
                    break;
                    case Expr::RecordInit:str(e.text);
                    countSize(e.args.size());
                    for(size_t i=0; i<e.args.size(); i++) {
                        str(e.names[i]);
                        ex(e.args[i]);
                    }
                    break;
                    case Expr::Variant:str(e.text); countSize(e.args.size()); for(auto&a:e.args)ex(a); break;
                    case Expr::Field:str(e.text);
                    ex(e.args[0]);
                    break;
                    case Expr::Ok:case Expr::Err:ty(e.annotation); ex(e.args[0]); break;
                    case Expr::Some:ty(e.annotation); ex(e.args[0]); break;
                    case Expr::None:ty(e.annotation); break;
                    case Expr::ClosureCall:
                        countSize(e.closureParams.size());
                        for(const auto& p:e.closureParams){str(p.name);ty(p.type);}
                        ty(e.annotation);
                        countSize(e.closureCaptures.size()); for(const auto& c:e.closureCaptures)str(c);
                        if(!e.closureBody)fail("E_WIRE","closure sin cuerpo",e.loc);
                        block(*e.closureBody);
                        countSize(e.args.size()); for(const auto& a:e.args)ex(a);
                        break;
                }
            }
            void block(const std::vector<Stmt>&b) {
                countSize(b.size());
                for(auto&s:b) {
                    byte(s.kind);
                    switch(s.kind) {
                        case Stmt::Let:case Stmt::Var:str(s.name);
                        ty(s.declared);
                        ex(s.expr);
                        break;
                        case Stmt::Assign:str(s.name);
                        ex(s.expr);
                        break;
                        case Stmt::Return:case Stmt::Print:ex(s.expr);
                        break;
                        case Stmt::TaskScope:block(s.body); break;
                        case Stmt::Spawn:str(s.name); ex(s.expr); break;
                        case Stmt::PrintText:str(s.text);
                        break;
                        case Stmt::If:ex(s.expr);
                        block(s.body);
                        block(s.other);
                        break;
                        case Stmt::Loop:ex(s.expr);
                        block(s.body);
                        break;
                        case Stmt::ForEach:str(s.name); ex(s.expr); block(s.body); break;
                        case Stmt::Destructure:countSize(s.names.size()); for(const auto&n:s.names)str(n); ex(s.expr); break;
                        case Stmt::Break:case Stmt::Continue:break;
                        case Stmt::Match:ex(s.expr); str(s.name); block(s.body); str(s.otherName); block(s.other); break;
                        case Stmt::MatchOption:ex(s.expr); str(s.name); block(s.body); block(s.other); break;
                        case Stmt::MatchEnum:ex(s.expr); countSize(s.arms.size()); for(size_t ai=0;ai<s.arms.size();++ai){str(s.armVariants[ai]);str(s.armNames[ai]);block(s.arms[ai]);} break;
                    }
                }
            }
        };
        class Reader  {
            const std::vector<uint8_t>&v;
            size_t p=0,nodes=0;
            void visit(int d) {
                if(d>OMNI_LIMIT_EXPR_HEIGHT)fail("E_LIMIT","Wire excede limites de nodos");
                if((++nodes&1023u)==0u)budgetCheck("el lector Wire");
            }
            public: bool old=false,wideNumbers=false,enumSupport=false,iterationSupport=false,a81ControlSupport=false,closureSupport=false,a85Support=false;
            explicit Reader(const std::vector<uint8_t>&x):v(x) {
            }
            uint8_t byte() {
                if(p==v.size())fail("E_WIRE","Wire truncado");
                return v[p++];
            }
            uint32_t u32() {
                uint32_t n=0;
                for(int i=0; i<4; i++)n|=uint32_t(byte())<<(8*i);
                return n;
            }
            uint64_t u64() { uint64_t n=0; for(int i=0;i<8;i++)n|=uint64_t(byte())<<(8*i); return n; }
            uint32_t count(uint32_t max) {
                auto n=u32();
                if(n>max)fail("E_LIMIT","longitud Wire excesiva");
                return n;
            }
            // The number of elements of a list: each element takes at least one byte, so a count larger than what is left to read is a truncated or forged input. No other number bounds it.
            uint32_t items() {
                auto n=u32();
                if(n>v.size()-p)fail("E_WIRE","Wire truncado: mas elementos que bytes");
                return n;
            }
            std::string str(uint32_t max=512) {
                auto n=count(max);
                if(n>v.size()-p)fail("E_WIRE","cadena Wire truncada");
                std::string s(reinterpret_cast<const char*>(v.data()+p),static_cast<size_t>(n));
                p+=static_cast<size_t>(n);
                validateUTF8(s);
                return s;
            }
            bool flag() {
                auto n=byte();
                if(n>1)fail("E_WIRE","flag binario invalido");
                return n;
            }
            Type ty() {
                if(old) {
                    auto t=byte();
                    if(t>1)fail("E_TYPE","tipo Wire desconocido");
                    return t==0?Type(Type::U32):Type(Type::Bool);
                }
                auto s=str();
                return s=="infer"?Type(Type::Unknown):parseType(s);
            }
            Expr ex(int d) {
                visit(d);
                Expr e;
                auto k=byte();
                if(k>(old?Expr::Binary:(a85Support?Expr::Close:(closureSupport?Expr::ClosureCall:(enumSupport?Expr::Variant:Expr::None)))))fail("E_WIRE","operacion Wire desconocida");
                e.kind=static_cast<Expr::Kind>(k);
                switch(e.kind) {
                    case Expr::Number:if(wideNumbers){e.annotation=ty();e.value=u64();}else{e.annotation=Type::U32;e.value=u32();} break;
                    case Expr::Boolean:e.value=u32(); break;
                    case Expr::Text:e.text=str(65536);
                    break;
                    case Expr::Ref:e.text=str();
                    break;
                    case Expr::Join:e.text=str(); break;
                    case Expr::Cancel:e.text=str(); break;
                    case Expr::Deadline:e.text=str(); e.args.push_back(ex(d+1)); break;
                    case Expr::Channel:e.annotation=ty(); e.args.push_back(ex(d+1)); break;
                    case Expr::Send:e.text=str(); e.args.push_back(ex(d+1)); break;
                    case Expr::Try:fail("E_VERSION","? no existe en las representaciones",e.loc);
                    case Expr::Receive:case Expr::Close:e.text=str(); break;
                    case Expr::Call:case Expr::Unary:case Expr::Binary: {
                        e.text=str();
                        auto n=items();
                        while(n--)e.args.push_back(ex(d+1));
                        break;
                    }
                    case Expr::RecordInit: {
                        e.text=str();
                        auto n=items();
                        while(n--) {
                            e.names.push_back(str());
                            e.args.push_back(ex(d+1));
                        }
                        break;
                    }
                    case Expr::Field:e.text=str();
                    e.args.push_back(ex(d+1));
                    break;
                    case Expr::Ok:case Expr::Err:e.annotation=ty(); e.args.push_back(ex(d+1)); break;
                    case Expr::Some:e.annotation=ty(); e.args.push_back(ex(d+1)); break;
                    case Expr::None:e.annotation=ty(); break;
                    case Expr::Variant:e.text=str(); {auto n=count(1);while(n--)e.args.push_back(ex(d+1));} break;
                    case Expr::ClosureCall: {
                        auto n=items(); while(n--){Param a; a.name=str();a.type=ty();e.closureParams.push_back(std::move(a));}
                        e.annotation=ty(); auto c=items();while(c--)e.closureCaptures.push_back(str());
                        e.closureBody=std::make_shared<std::vector<Stmt>>(block(d+1));
                        auto a=items();while(a--)e.args.push_back(ex(d+1));
                        break;
                    }
                }
                return e;
            }
            std::vector<Stmt>block(int d) {
                if(d>OMNI_LIMIT_BLOCK_DEPTH)fail("E_LIMIT","bloques Wire demasiado profundos");
                auto n=items();
                std::vector<Stmt>b;
                while(n--) {
                    visit(d);
                    Stmt s;
                    auto k=byte();
                    if(!iterationSupport&&k==static_cast<uint8_t>(Stmt::ForEach))fail("E_VERSION","for-in requiere OMC11");
                    if(!a81ControlSupport&&(k==static_cast<uint8_t>(Stmt::Destructure)||k==static_cast<uint8_t>(Stmt::Break)||k==static_cast<uint8_t>(Stmt::Continue)))
                        fail("E_VERSION","statement A81.3 requiere OMC15");
                    if(k>(old?Stmt::PrintText:(a85Support?Stmt::Spawn:(a81ControlSupport?Stmt::Continue:(iterationSupport?Stmt::ForEach:(enumSupport?Stmt::MatchEnum:Stmt::MatchOption))))))fail("E_WIRE","instruccion Wire desconocida");
                    s.kind=static_cast<Stmt::Kind>(k);
                    switch(s.kind) {
                        case Stmt::Let:case Stmt::Var:s.name=str();
                        s.declared=ty();
                        s.expr=ex(1);
                        break;
                        case Stmt::Assign:s.name=str();
                        s.expr=ex(1);
                        break;
                        case Stmt::Return:case Stmt::Print:s.expr=ex(1);
                        break;
                        case Stmt::TaskScope:s.body=block(d+1); break;
                        case Stmt::Spawn:s.name=str(); s.expr=ex(1); break;
                        case Stmt::PrintText:s.text=str(4096);
                        break;
                        case Stmt::If:s.expr=ex(1);
                        s.body=block(d+1);
                        s.other=block(d+1);
                        break;
                        case Stmt::Loop:s.expr=ex(1);
                        s.body=block(d+1);
                        break;
                        case Stmt::ForEach:s.name=str(); s.expr=ex(1); s.body=block(d+1); break;
                        case Stmt::Destructure:{auto a=count(16);while(a--)s.names.push_back(str());s.expr=ex(1);} break;
                        case Stmt::Break:case Stmt::Continue:break;
                        case Stmt::Match:s.expr=ex(1); s.name=str(); s.body=block(d+1); s.otherName=str(); s.other=block(d+1); break;
                        case Stmt::MatchOption:s.expr=ex(1); s.name=str(); s.body=block(d+1); s.other=block(d+1); break;
                        case Stmt::MatchEnum:s.expr=ex(1); {auto a=items();while(a--){s.armVariants.push_back(str());s.armNames.push_back(str());s.arms.push_back(block(d+1));s.armBindings.push_back(-1);s.armVariantIndices.push_back(-1);s.armPayloadFields.push_back(-1);}} break;
                    }
                    b.push_back(std::move(s));
                }
                return b;
            }
            bool done() {
                return p==v.size();
            }
        };
    }
    std::vector<const ThreadLocalDef*> orderedThreadLocals(const Program& p) {
        std::vector<const ThreadLocalDef*> out;
        for(const auto& m:p.modules)for(const auto& d:p.threadLocals)if(d.module==m.name)out.push_back(&d);
        return out;
    }
    std::string wave(const Program&p,IdentityProjection projection) {
        if(!p.authoringSource.empty()) {
            std::string capsule="(omni-wave 22 (authoring-source";
            for(size_t at=0;at<p.authoringSource.size();) {
                size_t end=std::min(at+4096,p.authoringSource.size());
                while(end<p.authoringSource.size()&&(static_cast<unsigned char>(p.authoringSource[end])&0xc0u)==0x80u)--end;
                capsule+=" "+quote(p.authoringSource.substr(at,end-at)); at=end;
            }
            capsule+="))\n";
            return capsule;
        }
        std::ostringstream o;
        const auto emittedVersion=emittedRepresentation(p,projection!=IdentityProjection::Onme2Compatibility);
        o<<"(omni-wave "<<emittedVersion<<"\n  (entry "<<p.module<<")";
        for(auto&m:p.modules) {
            o<<"\n  (module "<<m.name<<"\n    (imports";
            for(auto&i:m.imports)o<<" ("<<i.alias<<" "<<i.target<<")";
            o<<")";
            for(auto&d:p.records)if(d.module==m.name) {
                o<<"\n    (struct "<<d.name<<" (visibility "<<(d.pub?"public":"private")<<") (fields";
                for(auto&f:d.fields)o<<" ("<<f.name<<" "<<typeName(f.type)<<")";
                o<<")"; if(d.packed)o<<" (packed)"; if(d.opaque)o<<" (opaque)"; if(d.externC)o<<" (extern)"; o<<")";
            }
            for(auto&d:p.enums)if(d.module==m.name) {
                o<<"\n    (enum "<<d.name<<" (visibility "<<(d.pub?"public":"private")<<") (variants";
                for(auto&v:d.variants){o<<" ("<<v.name; if(v.hasPayload)o<<" "<<typeName(v.payload); o<<")";}
                o<<"))";
            }
            for(auto&d:p.threadLocals)if(d.module==m.name)
                o<<"\n    (thread-local "<<d.name<<" "<<typeName(d.type)<<" "<<(d.negative?"-":"")<<d.magnitude<<")";
            for(auto&f:p.functions)if(f.module==m.name&&!f.closureGenerated) {
                o<<"\n    (func "<<f.name<<" (visibility "<<(f.pub?"public":"private")<<")";
                if(f.linkage()) {
                    o<<" (linkage";
                    if(!f.exportName.empty())o<<" (export "<<quote(f.exportName)<<")";
                    if(f.isExtern)o<<" (extern "<<quote(f.externName)<<")";
                    if(!f.section.empty())o<<" (section "<<quote(f.section)<<")";
                    if(f.noInline)o<<" (noinline)";
                    o<<")";
                }
                o<<"\n      (params";
                for(auto&a:f.params){ o<<" ("; if(!a.receiverMode.empty())o<<a.receiverMode<<" "; o<<a.name<<" "<<typeName(a.type)<<")"; }
                o<<") (result "<<typeName(f.result)<<") (effects";
                if(f.capabilities.empty()) o<<" pure"; else for(const auto& cap:f.capabilities)o<<" "<<cap;
                o<<")\n      ";
                wb(o,f.body,3);
                o<<")";
            }
            o<<")";
        }
        o<<")\n";
        return o.str();
    }
    Program parseWave(const std::string&input) {
        validateUTF8(input);
        auto x=SParser(input).run();
        if(tag(x)!="omni-wave"||x.children.size()<3)fail("E_WAVE","cabecera Wave invalida");
        auto waveVersion=number64(x.children[1]);
        if(waveVersion==22) {
            form(x,"omni-wave",3);
            const auto& payload=x.children[2];
            if(tag(payload)!="authoring-source"||payload.children.size()<2)fail("E_WAVE","authoring source required");
            std::string source;
            for(size_t i=1;i<payload.children.size();++i)source+=atom(payload.children[i],true);
            Program capsule=parseParticleProgram(source);
            if(!capsule.bundled)for(const auto& m:capsule.modules)if(!m.imports.empty())fail("E_IMPORT_PATH","authoring capsule must be self contained");
            capsule.authoringSource=source; capsule.representationVersion=22; return capsule;
        }
        if(x.children.size()==3&&tag(x.children[2])=="authoring-source")fail("E_VERSION","authoring capsule requires Wave22");
        Program p;
        p.representationVersion=static_cast<uint32_t>(waveVersion);
        if(waveVersion==1) {
            form(x.children[2],"module",2);
            p.module=atom(x.children[2].children[1]);
            p.modules.push_back( {
                p.module, {
                }
            });
            for(size_t i=3; i<x.children.size(); i++)p.functions.push_back(rf(x.children[i],p.module,true));
            // v1 is readable for its historical scalar grammar; new constructs require v2.
            auto scalar=[](const Type&t) {
                return t.kind==Type::U32||t.kind==Type::Bool;
            };
            std::function<void(const Expr&)> legacyExpr=[&](const Expr&e) {
                if(e.kind>Expr::Binary)fail("E_VERSION","operacion requiere Wave 2",e.loc);
                for(auto&a:e.args)legacyExpr(a);
            };
            std::function<void(const std::vector<Stmt>&)> legacyBlock=[&](const std::vector<Stmt>&b) {
                for(auto&s:b) {
                    if(s.kind>Stmt::PrintText)fail("E_VERSION","instruccion requiere Wave 2",s.loc);
                    if(s.declared!=Type::Unknown&&!scalar(s.declared))fail("E_VERSION","tipo requiere Wave 2",s.loc);
                    legacyExpr(s.expr);
                    legacyBlock(s.body);
                    legacyBlock(s.other);
                }
            };
            for(auto&f:p.functions) {
                if(!scalar(f.result))fail("E_VERSION","tipo requiere Wave 2",f.loc);
                for(auto&a:f.params)if(!scalar(a.type))fail("E_VERSION","tipo requiere Wave 2",a.loc);
                legacyBlock(f.body);
            }
            return p;
        }
        if(waveVersion!=2&&waveVersion!=3&&waveVersion!=4&&waveVersion!=5&&waveVersion!=6&&waveVersion!=7&&waveVersion!=8&&waveVersion!=9&&waveVersion!=10&&waveVersion!=11&&waveVersion!=12&&waveVersion!=13&&waveVersion!=14&&waveVersion!=15&&waveVersion!=16&&waveVersion!=17&&waveVersion!=18&&waveVersion!=19&&waveVersion!=20&&waveVersion!=21)fail("E_VERSION","version Wave no soportada");
        form(x.children[2],"entry",2);
        p.module=atom(x.children[2].children[1]);
        for(size_t i=3; i<x.children.size(); i++) {
            auto&u=x.children[i];
            if(tag(u)!="module"||u.children.size()<3)fail("E_WAVE","modulo invalido",u.loc);
            ModuleInfo m;
            m.name=atom(u.children[1]);
            auto&imp=u.children[2];
            if(tag(imp)!="imports")fail("E_WAVE","imports requerido",u.loc);
            for(size_t j=1; j<imp.children.size(); j++) {
                auto&a=imp.children[j];
                if(!a.list||a.children.size()!=2)fail("E_WAVE","import invalido",a.loc);
                m.imports.push_back( {
                    atom(a.children[0]),"",atom(a.children[1]),a.loc
                });
            }
            for(size_t j=3; j<u.children.size(); j++) {
                auto&y=u.children[j];
                if(tag(y)=="func")p.functions.push_back(rf(y,m.name,false));
                else if(tag(y)=="enum") {
                    form(y,"enum",4); EnumDef d; d.name=atom(y.children[1]); d.module=m.name; d.pub=visibility(y.children[2]); d.loc=y.loc; auto&vs=y.children[3]; if(tag(vs)!="variants")fail("E_WAVE","variants requerido",vs.loc);
                    for(size_t k=1;k<vs.children.size();++k){auto&a=vs.children[k];if(!a.list||(a.children.size()!=1&&a.children.size()!=2))fail("E_WAVE","variante invalida",a.loc);VariantDef vd;vd.name=atom(a.children[0]);vd.loc=a.loc;if(a.children.size()==2){vd.hasPayload=true;vd.payload=parseType(atom(a.children[1]),a.loc);}d.variants.push_back(vd);}
                    p.enums.push_back(std::move(d));
                }
                else if(tag(y)=="thread-local") {
                    form(y,"thread-local",4);
                    ThreadLocalDef d; d.name=atom(y.children[1]); d.module=m.name; d.loc=y.loc; d.type=parseType(atom(y.children[2]),y.loc);
                    auto lit=atom(y.children[3]);
                    if(!lit.empty()&&lit[0]=='-') { d.negative=true; lit=lit.substr(1); }
                    if(lit.empty()||lit.size()>20)fail("E_WAVE","valor thread-local invalido",y.loc);
                    uint64_t v=0; for(char c:lit) { if(c<'0'||c>'9')fail("E_WAVE","valor thread-local invalido",y.loc); const uint64_t dg=uint64_t(c-'0'); if(v>(UINT64_MAX-dg)/10)fail("E_WAVE","valor thread-local excede u64",y.loc); v=v*10+dg; }
                    d.magnitude=v;
                    p.threadLocals.push_back(std::move(d));
                }
                else if(tag(y)=="struct") {
                    if(y.children.size()>=5&&y.children.size()<=7) {
                        bool sawPacked=false,sawOpaque=false,sawExtern=false;
                        for(size_t k=4;k<y.children.size();++k) {
                            const auto mark=tag(y.children[k]);
                            if((mark!="packed"&&mark!="opaque"&&mark!="extern")||y.children[k].children.size()!=1||(mark=="packed"?sawPacked:(mark=="opaque"?sawOpaque:sawExtern)))fail("E_WAVE","marca de struct invalida",y.loc);
                            (mark=="packed"?sawPacked:(mark=="opaque"?sawOpaque:sawExtern))=true;
                        }
                    } else form(y,"struct",4);
                    RecordDef r;
                    for(size_t k=4;k<y.children.size();++k) { const auto mark=tag(y.children[k]); if(mark=="packed")r.packed=true; else if(mark=="opaque")r.opaque=true; else r.externC=true; }
                    r.name=atom(y.children[1]);
                    r.module=m.name;
                    r.pub=visibility(y.children[2]);
                    r.loc=y.loc;
                    auto&f=y.children[3];
                    if(tag(f)!="fields")fail("E_WAVE","fields requerido",y.loc);
                    for(size_t k=1; k<f.children.size(); k++) {
                        auto&a=f.children[k];
                        if(!a.list||a.children.size()!=2)fail("E_WAVE","campo invalido",a.loc);
                        r.fields.push_back( {
                            atom(a.children[0]),parseType(atom(a.children[1]),a.loc),a.loc
                        });
                    }
                    p.records.push_back(std::move(r));
                }
                else fail("E_WAVE","declaracion desconocida",y.loc);
            }
            p.modules.push_back(std::move(m));
        }
        p.bundled=p.modules.size()>1;
        if(waveVersion==2) {
            std::function<void(const Type&,Loc)> noTextType=[&](const Type&t,Loc l){
                if(t.kind==Type::Text)fail("E_VERSION","Text requiere Wave 3",l);
                for(auto &q:t.parts)noTextType(q,l);
            };
            std::function<void(const Expr&)> noTextExpr=[&](const Expr&e){
                if(e.kind==Expr::Text)fail("E_VERSION","literal Text requiere Wave 3",e.loc);
                for(auto &a:e.args)noTextExpr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noTextBlock=[&](const std::vector<Stmt>&b){
                for(auto &st:b){ noTextType(st.declared,st.loc); noTextExpr(st.expr); noTextBlock(st.body); noTextBlock(st.other); }
            };
            for(auto &d:p.records)for(auto &f:d.fields)noTextType(f.type,f.loc);
            for(auto &f:p.functions){ noTextType(f.result,f.loc); for(auto &a:f.params)noTextType(a.type,a.loc); noTextBlock(f.body); }
        }
        if(waveVersion==3) {
            auto legacy=legacyIoCapabilities();
            for(auto& f:p.functions) if(!f.capabilities.empty() && f.capabilities!=legacy) fail("E_VERSION","capabilities especificas requieren Wave 4",f.loc);
        }
        if(waveVersion==4) {
            // Historical Wave4 used data.read/data.write for file I/O before dev.6 split fs.* from governed data.*.
            // Migrate the historical meaning once, then canonical Wave5 prints fs.read/fs.write.
            for(auto& f:p.functions) {
                if(f.capabilities.erase("data.read")) f.capabilities.insert("fs.read");
                if(f.capabilities.erase("data.write")) f.capabilities.insert("fs.write");
            }
        }
        if(waveVersion<5){
            std::function<void(const Type&,Loc)> noDev6=[&](const Type&t,Loc l){ if(t.kind==Type::Bytes||t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::Future||t.kind==Type::Stream)fail("E_VERSION","Bytes/Resource/Future/Stream requieren Wave 5",l); for(auto&q:t.parts)noDev6(q,l); };
            std::function<void(const Expr&)> noDev6Expr=[&](const Expr&e){ if(e.kind==Expr::Call&&(e.text=="move"||e.text=="borrow"||e.text.rfind("bytes.",0)==0||e.text.rfind("buffer.",0)==0))fail("E_VERSION","operacion Bytes/Resource requiere Wave 5",e.loc); for(auto&a:e.args)noDev6Expr(a); };
            std::function<void(const std::vector<Stmt>&)> noDev6Block=[&](const std::vector<Stmt>&b){for(auto&st:b){noDev6(st.declared,st.loc);noDev6Expr(st.expr);noDev6Block(st.body);noDev6Block(st.other);}};
            for(auto&d:p.records)for(auto&f:d.fields)noDev6(f.type,f.loc);
            for(auto&f:p.functions){noDev6(f.result,f.loc);for(auto&a:f.params)noDev6(a.type,a.loc);noDev6Block(f.body);}
        }
        if(waveVersion<6){
            std::function<void(const Type&,Loc)> noOption=[&](const Type&t,Loc l){ if(t.kind==Type::Option)fail("E_VERSION","Option requiere Wave 6",l); for(auto&q:t.parts)noOption(q,l); };
            std::function<void(const Expr&)> noOptionExpr=[&](const Expr&e){ if(e.kind==Expr::Some||e.kind==Expr::None)fail("E_VERSION","Some/None requieren Wave 6",e.loc); for(auto&a:e.args)noOptionExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noOptionBlock=[&](const std::vector<Stmt>&b){for(auto&st:b){ if(st.kind==Stmt::MatchOption)fail("E_VERSION","match Option requiere Wave 6",st.loc); noOption(st.declared,st.loc); noOptionExpr(st.expr); noOptionBlock(st.body); noOptionBlock(st.other); }};
            for(auto&d:p.records)for(auto&f:d.fields)noOption(f.type,f.loc);
            for(auto&f:p.functions){noOption(f.result,f.loc);for(auto&a:f.params)noOption(a.type,a.loc);noOptionBlock(f.body);}
        }
        if(waveVersion<7){
            std::function<void(const Type&,Loc)> noWideInt=[&](const Type&t,Loc l){ if(isInteger(t)&&t.kind!=Type::U32)fail("E_VERSION","tipos enteros extendidos requieren Wave 7",l); for(auto&q:t.parts)noWideInt(q,l); };
            std::function<void(const Expr&)> noWideExpr=[&](const Expr&e){ if(e.kind==Expr::Number&&e.annotation.kind!=Type::Unknown&&e.annotation.kind!=Type::U32)fail("E_VERSION","literales enteros extendidos requieren Wave 7",e.loc); for(auto&a:e.args)noWideExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noWideBlock=[&](const std::vector<Stmt>&b){for(auto&st:b){noWideInt(st.declared,st.loc);noWideExpr(st.expr);noWideBlock(st.body);noWideBlock(st.other);}};
            for(auto&d:p.records)for(auto&f:d.fields)noWideInt(f.type,f.loc);
            for(auto&f:p.functions){noWideInt(f.result,f.loc);for(auto&a:f.params)noWideInt(a.type,a.loc);noWideBlock(f.body);}
        }

        if(waveVersion<8){
            if(!p.enums.empty())fail("E_VERSION","enum requiere Wave 8");
            std::function<void(const Expr&)> noEnumExpr=[&](const Expr&e){if(e.kind==Expr::Variant)fail("E_VERSION","constructor enum requiere Wave 8",e.loc);for(auto&a:e.args)noEnumExpr(a);};
            std::function<void(const std::vector<Stmt>&)> noEnumBlock=[&](const std::vector<Stmt>&b){for(auto&st:b){if(st.kind==Stmt::MatchEnum)fail("E_VERSION","match enum requiere Wave 8",st.loc);noEnumExpr(st.expr);noEnumBlock(st.body);noEnumBlock(st.other);for(auto&arm:st.arms)noEnumBlock(arm);}};
            for(auto&f:p.functions)noEnumBlock(f.body);
        }
        if(waveVersion<9){
            std::function<void(const Type&,Loc)> noProductType=[&](const Type&t,Loc l){ if(t.kind==Type::Tuple||t.kind==Type::Array)fail("E_VERSION","Tuple/Array requieren Wave 9",l); for(auto&q:t.parts)noProductType(q,l); };
            std::function<void(const Expr&)> noProductExpr=[&](const Expr&e){ if(e.kind==Expr::Call&&(e.text=="tuple"||e.text.rfind("tuple.",0)==0||e.text=="array"||e.text.rfind("array.",0)==0))fail("E_VERSION","operacion Tuple/Array requiere Wave 9",e.loc); for(auto&a:e.args)noProductExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noProductBlock=[&](const std::vector<Stmt>&b){ for(auto&st:b){ noProductType(st.declared,st.loc); noProductExpr(st.expr); noProductBlock(st.body); noProductBlock(st.other); for(auto&arm:st.arms)noProductBlock(arm); } };
            for(auto&d:p.records)for(auto&f:d.fields)noProductType(f.type,f.loc);
            for(auto&d:p.enums)for(auto&v:d.variants)if(v.hasPayload)noProductType(v.payload,v.loc);
            for(auto&f:p.functions){ noProductType(f.result,f.loc); for(auto&a:f.params)noProductType(a.type,a.loc); noProductBlock(f.body); }
        }
        if(waveVersion<10){
            std::function<void(const Type&,Loc)> noViewType=[&](const Type&t,Loc l){ if(t.kind==Type::View)fail("E_VERSION","View requiere Wave 10",l); for(auto&q:t.parts)noViewType(q,l); };
            std::function<void(const Expr&)> noViewExpr=[&](const Expr&e){ if(e.kind==Expr::Call&&(e.text=="view"||e.text.rfind("view.",0)==0))fail("E_VERSION","operacion View requiere Wave 10",e.loc); for(auto&a:e.args)noViewExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noViewBlock=[&](const std::vector<Stmt>&b){ for(auto&st:b){ noViewType(st.declared,st.loc); noViewExpr(st.expr); noViewBlock(st.body); noViewBlock(st.other); for(auto&arm:st.arms)noViewBlock(arm); } };
            for(auto&d:p.records)for(auto&f:d.fields)noViewType(f.type,f.loc);
            for(auto&d:p.enums)for(auto&variant:d.variants)if(variant.hasPayload)noViewType(variant.payload,variant.loc);
            for(auto&f:p.functions){ noViewType(f.result,f.loc); for(auto&a:f.params)noViewType(a.type,a.loc); noViewBlock(f.body); }
        }
        if(waveVersion<11){
            std::function<void(const std::vector<Stmt>&)> noIter=[&](const std::vector<Stmt>&b){ for(auto&st:b){ if(st.kind==Stmt::ForEach)fail("E_VERSION","for-in requiere Wave 11",st.loc); noIter(st.body); noIter(st.other); for(auto&arm:st.arms)noIter(arm); } };
            for(auto&f:p.functions)noIter(f.body);
        }
        if(waveVersion<12){
            std::function<void(const Type&,Loc)> noAlpha8LoanType=[&](const Type&t,Loc l){ if(t.kind==Type::BorrowMut)fail("E_VERSION","BorrowMut requiere Wave 12",l); for(const auto&q:t.parts)noAlpha8LoanType(q,l); };
            std::function<void(const Expr&)> noAlpha8LoanExpr=[&](const Expr&e){ if(e.kind==Expr::Call&&e.text=="borrow_mut")fail("E_VERSION","borrow_mut requiere Wave 12",e.loc); for(const auto&a:e.args)noAlpha8LoanExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noAlpha8LoanBlock=[&](const std::vector<Stmt>&b){
                for(const auto&st:b){
                    noAlpha8LoanType(st.declared,st.loc);
                    noAlpha8LoanExpr(st.expr);
                    if((st.kind==Stmt::Let||st.kind==Stmt::Var)&&st.expr.kind==Expr::Call&&(st.expr.text=="borrow"||st.expr.text=="borrow_mut"))
                        fail("E_VERSION","prestamos locales persistentes requieren Wave 12",st.loc);
                    noAlpha8LoanBlock(st.body); noAlpha8LoanBlock(st.other); for(const auto&arm:st.arms)noAlpha8LoanBlock(arm);
                }
            };
            for(const auto&d:p.records)for(const auto&field:d.fields)noAlpha8LoanType(field.type,field.loc);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noAlpha8LoanType(v.payload,v.loc);
            for(const auto&fn:p.functions){ noAlpha8LoanType(fn.result,fn.loc); for(const auto&a:fn.params)noAlpha8LoanType(a.type,a.loc); noAlpha8LoanBlock(fn.body); }
        }
        if(waveVersion<13){
            std::function<void(const Type&,Loc)> noFloatType=[&](const Type&t,Loc l){ if(isFloat(t))fail("E_VERSION","f32/f64 requieren Wave 13",l); for(const auto&q:t.parts)noFloatType(q,l); };
            std::function<void(const Expr&)> noFloatExpr=[&](const Expr&e){ if(e.kind==Expr::Number&&isFloat(e.annotation))fail("E_VERSION","literal float requiere Wave 13",e.loc); if(e.kind==Expr::Call&&(e.text=="f32"||e.text=="f64"))fail("E_VERSION","cast float requiere Wave 13",e.loc); for(const auto&a:e.args)noFloatExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noFloatBlock=[&](const std::vector<Stmt>&b){ for(const auto&st:b){ noFloatType(st.declared,st.loc); noFloatExpr(st.expr); noFloatBlock(st.body); noFloatBlock(st.other); for(const auto&arm:st.arms)noFloatBlock(arm); } };
            for(const auto&d:p.records)for(const auto&field:d.fields)noFloatType(field.type,field.loc);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noFloatType(v.payload,v.loc);
            for(const auto&fn:p.functions){ noFloatType(fn.result,fn.loc); for(const auto&a:fn.params)noFloatType(a.type,a.loc); noFloatBlock(fn.body); }
        }
        if(waveVersion<14){
            std::function<void(const Type&,Loc)> noUnicodeType=[&](const Type&t,Loc l){ if(t.kind==Type::Char)fail("E_VERSION","Char requiere Wave 14",l); for(const auto&q:t.parts)noUnicodeType(q,l); };
            std::function<void(const Expr&)> noUnicodeExpr=[&](const Expr&e){
                if(e.kind==Expr::Call&&(e.text=="char.from_u32"||e.text=="char.codepoint"||e.text=="text.from_char"||e.text=="text.equals"||e.text=="text.byte_len"||e.text=="text.scalar_len"||e.text=="text.scalar_at"))
                    fail("E_VERSION","Unicode scalar/Text API requiere Wave 14",e.loc);
                for(const auto&a:e.args)noUnicodeExpr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noUnicodeBlock=[&](const std::vector<Stmt>&b){ for(const auto&st:b){ noUnicodeType(st.declared,st.loc); noUnicodeExpr(st.expr); noUnicodeBlock(st.body); noUnicodeBlock(st.other); for(const auto&arm:st.arms)noUnicodeBlock(arm); } };
            for(const auto&d:p.records)for(const auto&field:d.fields)noUnicodeType(field.type,field.loc);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noUnicodeType(v.payload,v.loc);
            for(const auto&fn:p.functions){ noUnicodeType(fn.result,fn.loc); for(const auto&a:fn.params)noUnicodeType(a.type,a.loc); noUnicodeBlock(fn.body); }
        }
        if(waveVersion<15){
            std::function<void(const Expr&)> noA813Expr=[&](const Expr&e){
                if(e.kind==Expr::Call&&e.text=="index")fail("E_VERSION","index syntax requiere Wave 15",e.loc);
                for(const auto&a:e.args)noA813Expr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noA813Block=[&](const std::vector<Stmt>&b){
                for(const auto&st:b){
                    if(st.kind==Stmt::Destructure||st.kind==Stmt::Break||st.kind==Stmt::Continue)
                        fail("E_VERSION","statement A81.3 requiere Wave 15",st.loc);
                    if((st.kind==Stmt::Match&&(st.name=="_"||st.otherName=="_"))||
                       (st.kind==Stmt::MatchOption&&st.name=="_")||
                       (st.kind==Stmt::MatchEnum&&std::find(st.armNames.begin(),st.armNames.end(),"_")!=st.armNames.end()))
                        fail("E_VERSION","wildcard pattern requiere Wave 15",st.loc);
                    noA813Expr(st.expr); noA813Block(st.body); noA813Block(st.other); for(const auto&arm:st.arms)noA813Block(arm);
                }
            };
            for(const auto&fn:p.functions)noA813Block(fn.body);
        }
        if(waveVersion<16){
            std::function<void(const Type&,Loc)> noRangeType=[&](const Type&t,Loc l){
                if(t.kind==Type::Range)fail("E_VERSION","Range requiere Wave 16",l);
                for(const auto&q:t.parts)noRangeType(q,l);
            };
            std::function<void(const Expr&)> noRangeExpr=[&](const Expr&e){
                if(e.kind==Expr::Call&&(e.text=="range.exclusive"||e.text=="range.inclusive"))
                    fail("E_VERSION","range syntax requiere Wave 16",e.loc);
                for(const auto&a:e.args)noRangeExpr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noRangeBlock=[&](const std::vector<Stmt>&b){
                for(const auto&st:b){
                    noRangeType(st.declared,st.loc); noRangeExpr(st.expr);
                    noRangeBlock(st.body); noRangeBlock(st.other); for(const auto&arm:st.arms)noRangeBlock(arm);
                }
            };
            for(const auto&d:p.records)for(const auto&field:d.fields)noRangeType(field.type,field.loc);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noRangeType(v.payload,v.loc);
            for(const auto&fn:p.functions){ noRangeType(fn.result,fn.loc); for(const auto&a:fn.params)noRangeType(a.type,a.loc); noRangeBlock(fn.body); }
        }
        if(waveVersion<17) {
            std::function<void(const Expr&)> noClosureExpr=[&](const Expr& e){
                if(e.kind==Expr::ClosureCall)fail("E_VERSION","closure-call requiere Wave 17",e.loc);
                for(const auto& a:e.args)noClosureExpr(a);
                if(e.closureBody)for(const auto& s:*e.closureBody)noClosureExpr(s.expr);
            };
            std::function<void(const std::vector<Stmt>&)> noClosureBlock=[&](const std::vector<Stmt>& b){
                for(const auto& s:b){ noClosureExpr(s.expr); noClosureBlock(s.body); noClosureBlock(s.other); for(const auto& arm:s.arms)noClosureBlock(arm); }
            };
            for(const auto& f:p.functions)noClosureBlock(f.body);
            for(const auto& f:p.functions)for(const auto& a:f.params)if(!a.receiverMode.empty())
                fail("E_VERSION","receiver mode requiere Wave 17",a.loc);
        }
        if(waveVersion<19)for(const auto& f:p.functions)if(a85Block(f.body))
            fail("E_VERSION","task_scope/spawn/join requieren Wave19",f.loc);
        if(waveVersion<20)for(const auto& f:p.functions)if(a86Block(f.body))
            fail("E_VERSION","host.read/host.write/host.process/host.tcp/host.ffi requieren Wave20",f.loc);
        if(waveVersion<21)for(const auto& f:p.functions)if(a87Function(p,f))
            fail("E_VERSION","Borrow/BorrowMut devuelto, bit.*, Option<Resource>, primitivas de maquina (raw/port/cpu/atomic) y recursos nominales requieren Wave21",f.loc);
        if(waveVersion<21&&!p.threadLocals.empty())fail("E_VERSION","thread_local requiere Wave21",p.threadLocals.front().loc);
        if(waveVersion<21)for(const auto& f:p.functions)if(f.linkage())fail("E_VERSION","atributos de enlace (export/extern/section/noinline) requieren Wave21",f.loc);
        if(waveVersion<21)for(const auto& r:p.records)if(r.packed)fail("E_VERSION","packed struct requiere Wave21",r.loc);
        if(waveVersion<21)for(const auto& r:p.records)if(r.opaque)fail("E_VERSION","opaque struct requiere Wave21",r.loc);
        if(waveVersion<21)for(const auto& r:p.records)if(r.externC)fail("E_VERSION","extern struct requiere Wave21",r.loc);
        if(waveVersion<21)for(const auto& r:p.records)for(const auto& field:r.fields)
            if(nominalResourceType(field.type))fail("E_VERSION","campo Resource nominal requiere Wave21",r.loc);
        if(waveVersion<21)for(const auto& r:p.records)for(const auto& field:r.fields)
            if(typeContainsPending(p,field.type,r.module))fail("E_VERSION","campo pending requiere Wave21",r.loc);
        if(waveVersion<21)for(const auto& r:p.records)for(const auto& field:r.fields)
            if(ownedTupleType(p,field.type,r.module))fail("E_VERSION","campo Tuple owning requiere Wave21",r.loc);
        if(waveVersion<21)for(const auto& en:p.enums)for(const auto& v:en.variants)
            if(v.hasPayload&&(typeContainsResource(p,v.payload,en.module)||typeContainsPending(p,v.payload,en.module)))fail("E_VERSION","enum con payload Resource/pending requiere Wave21",en.loc);
        return p;
    }
    // The signature of a generic template keeps the nominal types as written (`Id`, `alias.Box<T>`). Their identity is module-qualified (TYPE_IDENTITY_0_2): resolve it in the scope of the template's own
    // module, with the import alias rule the expander uses. A name that is a generic parameter or names nothing known stays unresolved: the checker refuses it and the projection fails closed.
    Type resolveOpenType(const Program&p,const std::string&module,const std::set<std::string>&bound,Type t) {
        for(auto&x:t.parts)x=resolveOpenType(p,module,bound,x);
        const bool keyed=t.kind==Type::Record||t.kind==Type::Enum,named=t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::BorrowMut;
        if((!keyed&&!named)||(keyed&&!t.key.empty())||bound.count(t.name))return t;
        std::string target=module,name=t.name;
        const auto dot=name.find('.');
        if(dot!=std::string::npos) {
            const auto alias=name.substr(0,dot);name=name.substr(dot+1);target.clear();
            for(const auto&m:p.modules)if(m.name==module)for(const auto&im:m.imports)if(im.alias==alias)target=im.target;
        }
        if(target.empty())return t;
        const auto key=target+"."+name;
        bool known=false;
        for(const auto&r:p.records)known=known||r.module+"."+r.name==key;     // by module and name: the key of a record is assigned later than the declaration of a template
        for(const auto&e:p.enums)known=known||e.module+"."+e.name==key;
        for(const auto&r:p.genericRecordTemplates)known=known||r.module+"."+r.name==key;
        for(const auto&e:p.genericEnumTemplates)known=known||e.module+"."+e.name==key;
        if(!known)return t;
        if(keyed)t.key=key;else t.name=key;
        return t;
    }
    uint32_t writerRepresentation(const Program&p) {
        return p.authoringSource.empty()?emittedRepresentation(p):22u;   // an authoring capsule is Wave22/OMC22; any other program takes the fence its content needs (18..21)
    }
    std::vector<uint8_t>wire(const Program&p) {
        if(!p.authoringSource.empty()) {
            Writer capsule;
            for(char c:std::string("OMCX"))capsule.byte(static_cast<uint8_t>(c));
            capsule.u32(22); capsule.str(p.authoringSource);
            return capsule.v;
        }
        Writer w;
        for(char c:std::string("OMCX"))w.byte(static_cast<uint8_t>(c));
        w.u32(emittedRepresentation(p)); // OMC20 fences hosted effects; OMC21 fences returned borrows.
        w.str(p.module);
        w.countSize(p.modules.size());
        for(auto&m:p.modules) {
            w.str(m.name);
            w.countSize(m.imports.size());
            for(auto&i:m.imports) {
                w.str(i.alias);
                w.str(i.target);
            }
            uint32_t n=0;
            for(auto&r:p.records)if(r.module==m.name)n++;
            w.u32(n);
            for(auto&r:p.records)if(r.module==m.name) {
                w.str(r.name);
                w.byte(static_cast<uint8_t>((r.pub?1:0)|(r.packed?2:0)|(r.opaque?4:0)|(r.externC?8:0)));
                w.countSize(r.fields.size());
                for(auto&f:r.fields) {
                    w.str(f.name);
                    w.ty(f.type);
                }
            }
            n=0;
            for(auto&d:p.enums)if(d.module==m.name)n++;
            w.u32(n);
            for(auto&d:p.enums)if(d.module==m.name){w.str(d.name);w.byte(d.pub);w.countSize(d.variants.size());for(auto&v:d.variants){w.str(v.name);w.byte(v.hasPayload);if(v.hasPayload)w.ty(v.payload);}}
            n=0;
            for(auto&f:p.functions)if(f.module==m.name&&!f.closureGenerated)n++;
            w.u32(n);
            for(auto&f:p.functions)if(f.module==m.name&&!f.closureGenerated) {
                w.str(f.name);
                w.byte(f.pub);
                w.ty(f.result);
                w.countSize(f.capabilities.size());
                for(const auto& cap:f.capabilities)w.str(cap);
                w.countSize(f.params.size());
                for(auto&a:f.params) {
                    w.str(a.receiverMode);
                    w.str(a.name);
                    w.ty(a.type);
                }
                w.block(f.body);
            }
        }
        if(!p.threadLocals.empty()) {
            w.str("TLS1"); w.countSize(p.threadLocals.size());
            for(const auto* d:orderedThreadLocals(p)) { w.str(d->module); w.str(d->name); w.ty(d->type); w.byte(d->negative); w.u64(d->magnitude); }
        }
        {
            size_t linked=0; for(const auto& f:p.functions)if(f.linkage()&&!f.closureGenerated)++linked;
            if(linked) {
                w.str("LNK1"); w.countSize(linked);
                for(const auto& f:p.functions)if(f.linkage()&&!f.closureGenerated) { w.str(f.module); w.str(f.name); w.byte(static_cast<uint8_t>((f.noInline?1:0)|(f.isExtern?2:0))); w.str(f.exportName); w.str(f.externName); w.str(f.section); }
            }
        }
        return w.v;
    }
    Program fromWire(const std::vector<uint8_t>&bytes) {
        Reader r(bytes);
        std::string physicalMagic;
        for(int i=0; i<4; i++)physicalMagic+=char(r.byte());
        std::string magic=physicalMagic;
        uint32_t representationVersion=0;
        if(physicalMagic=="OMCX") {
            const auto version=r.u32();
            if(version==22) {
                const auto source=r.str(std::numeric_limits<uint32_t>::max());
                if(!r.done())fail("E_WIRE","datos adicionales en authoring capsule");
                Program capsule=parseParticleProgram(source);
                if(!capsule.bundled)for(const auto& m:capsule.modules)if(!m.imports.empty())fail("E_IMPORT_PATH","authoring capsule must be self contained");
                capsule.authoringSource=source; capsule.representationVersion=22; return capsule;
            }
            if(version!=10&&version!=11&&version!=12&&version!=13&&version!=14&&version!=15&&version!=16&&version!=17&&version!=18&&version!=19&&version!=20&&version!=21)fail("E_VERSION","version Wire extendida no soportada");
            if(bytes.size()>=19&&(std::string(bytes.begin()+12,bytes.begin()+19)=="bundle "||std::string(bytes.begin()+12,bytes.begin()+19)=="module "))
                fail("E_VERSION","authoring capsule requires OMC22");
            representationVersion=version;
            magic="OMC"+std::to_string(version);
        }
        if(magic!="OMC1"&&magic!="OMC2"&&magic!="OMC3"&&magic!="OMC4"&&magic!="OMC5"&&magic!="OMC6"&&magic!="OMC7"&&magic!="OMC8"&&magic!="OMC9"&&magic!="OMC10"&&magic!="OMC11"&&magic!="OMC12"&&magic!="OMC13"&&magic!="OMC14"&&magic!="OMC15"&&magic!="OMC16"&&magic!="OMC17"&&magic!="OMC18"&&magic!="OMC19"&&magic!="OMC20"&&magic!="OMC21")fail("E_VERSION","cabecera Wire no soportada");
        if(!representationVersion)representationVersion=static_cast<uint32_t>(std::stoul(magic.substr(3)));
        r.old=magic=="OMC1";
        r.wideNumbers=representationVersion>=7;
        r.enumSupport=representationVersion>=8;
        r.iterationSupport=representationVersion>=11;
        r.a81ControlSupport=representationVersion>=15;
        r.closureSupport=representationVersion>=17;
        r.a85Support=representationVersion>=19;
        Program p;
        p.representationVersion=representationVersion;
        p.module=r.str(128);
        auto readFunctions=[&](const std::string&mod) {
            auto n=r.items();
            while(n--) {
                Function f;
                f.module=mod;
                f.name=r.str(128);
                if(!r.old)f.pub=r.flag();
                f.result=r.ty();
                if(representationVersion>=4) {
                    auto cn=r.items();
                    while(cn--){ auto raw=r.str(64); auto cap=canonicalCapability(raw); if(!isKnownCapability(cap))fail("E_CAPABILITY","capability Wire desconocida: "+raw); f.capabilities.insert(cap); }
                    } else {
                    auto ef=r.byte();
                    if(ef>1)fail("E_EFFECT","efecto Wire desconocido");
                    if(ef) { auto xs=legacyIoCapabilities(); f.capabilities.insert(xs.begin(),xs.end()); }
                }
                auto a=r.items();
                while(a--) {
                    Param x;
                    if(r.closureSupport)x.receiverMode=r.str(16);
                    x.name=r.str(128);
                    x.type=r.ty();
                    f.params.push_back(x);
                }
                f.body=r.block(1);
                p.functions.push_back(std::move(f));
            }
        };
        if(r.old) {
            p.modules.push_back( {
                p.module, {
                }
            });
            readFunctions(p.module);
        }
        else {
            auto n=r.items();
            while(n--) {
                ModuleInfo m;
                m.name=r.str(128);
                auto a=r.items();
                while(a--) {
                    Import im;
                    im.alias=r.str(128);
                    im.target=r.str(128);
                    m.imports.push_back(im);
                }
                auto defs=r.items();
                while(defs--) {
                    RecordDef d;
                    d.module=m.name;
                    d.name=r.str(128);
                    { const auto fl=r.byte(); if(fl>15)fail("E_WIRE","flags de struct invalidos"); d.pub=(fl&1)!=0; d.packed=(fl&2)!=0; d.opaque=(fl&4)!=0; d.externC=(fl&8)!=0; }
                    auto fs=r.items();
                    while(fs--) {
                        FieldDef f;
                        f.name=r.str(128);
                        f.type=r.ty();
                        d.fields.push_back(f);
                    }
                    p.records.push_back(d);
                }
                if(representationVersion>=8){auto es=r.items();while(es--){EnumDef d;d.module=m.name;d.name=r.str(128);d.pub=r.flag();auto vs=r.count(static_cast<uint32_t>(OMNI_ENUM_MAX_VARIANTS));while(vs--){VariantDef vd;vd.name=r.str(128);vd.hasPayload=r.flag();if(vd.hasPayload)vd.payload=r.ty();d.variants.push_back(vd);}p.enums.push_back(std::move(d));}}
                readFunctions(m.name);
                p.modules.push_back(std::move(m));
            }
        }
        bool sawTls=false,sawLinkage=false;
        while(!r.done()) {
            const auto trailer=r.str(8);
            if(trailer=="TLS1"&&!sawTls&&!sawLinkage) {
                sawTls=true;
                auto tn=r.items();
                while(tn--) {
                    ThreadLocalDef d; d.module=r.str(128); d.name=r.str(128); d.type=r.ty(); d.negative=r.flag(); d.magnitude=r.u64();
                    p.threadLocals.push_back(std::move(d));
                }
                if(p.threadLocals.empty())fail("E_WIRE","seccion thread-local vacia");
            } else if(trailer=="LNK1"&&!sawLinkage) {
                sawLinkage=true;
                auto ln=r.items();
                if(ln==0)fail("E_WIRE","seccion de enlace vacia");
                std::unordered_map<std::string,Function*> byName;                  // the last function of a name wins, as the scan it replaces
                for(auto& f:p.functions)byName[f.module+std::string(1,'\0')+f.name]=&f;
                while(ln--) {
                    const auto module=r.str(128); const auto name=r.str(128); const auto flags=r.byte();
                    if(flags>3)fail("E_WIRE","flags de enlace invalidos");
                    const auto exportName=r.str(256); const auto externName=r.str(256); const auto section=r.str(256);
                    Function* target=nullptr; { const auto it=byName.find(module+std::string(1,'\0')+name); if(it!=byName.end())target=it->second; }
                    if(!target)fail("E_WIRE","la seccion de enlace nombra una funcion que no existe: "+module+"."+name);
                    if(target->linkage())fail("E_WIRE","enlace repetido para "+module+"."+name);
                    target->noInline=(flags&1)!=0; target->isExtern=(flags&2)!=0; target->exportName=exportName; target->externName=externName; target->section=section;
                    if(target->isExtern==externName.empty())fail("E_WIRE","extern inconsistente en la seccion de enlace");
                    if(!target->linkage())fail("E_WIRE","entrada de enlace sin atributos");
                }
            } else fail("E_WIRE","bytes adicionales al final");
        }
        if(!r.done())fail("E_WIRE","bytes adicionales al final");
        p.bundled=p.modules.size()>1;
        if(magic=="OMC2") {
            std::function<void(const Type&)> noTextType=[&](const Type&t){ if(t.kind==Type::Text)fail("E_VERSION","Text requiere OMC3"); for(auto &q:t.parts)noTextType(q); };
            std::function<void(const Expr&)> noTextExpr=[&](const Expr&e){ if(e.kind==Expr::Text)fail("E_VERSION","literal Text requiere OMC3"); for(auto &a:e.args)noTextExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noTextBlock=[&](const std::vector<Stmt>&b){ for(auto &st:b){ noTextType(st.declared); noTextExpr(st.expr); noTextBlock(st.body); noTextBlock(st.other); } };
            for(auto &d:p.records)for(auto &f:d.fields)noTextType(f.type);
            for(auto &f:p.functions){ noTextType(f.result); for(auto &a:f.params)noTextType(a.type); noTextBlock(f.body); }
        }
        if(magic=="OMC3") {
            auto legacy=legacyIoCapabilities();
            for(auto& f:p.functions) if(!f.capabilities.empty() && f.capabilities!=legacy) fail("E_VERSION","capabilities especificas requieren OMC4");
        }
        if(magic=="OMC4") {
            // Historical OMC4 capability migration, matching Wave4 semantics.
            for(auto& f:p.functions) {
                if(f.capabilities.erase("data.read")) f.capabilities.insert("fs.read");
                if(f.capabilities.erase("data.write")) f.capabilities.insert("fs.write");
            }
        }
        if(representationVersion<5) {
            std::function<void(const Type&)> noDev6=[&](const Type&t){if(t.kind==Type::Bytes||t.kind==Type::Resource||t.kind==Type::Borrow||t.kind==Type::Future||t.kind==Type::Stream)fail("E_VERSION","Bytes/Resource/Future/Stream requieren OMC5");for(auto&q:t.parts)noDev6(q);};
            std::function<void(const Expr&)> noDev6Expr=[&](const Expr&e){if(e.kind==Expr::Call&&(e.text=="move"||e.text=="borrow"||e.text.rfind("bytes.",0)==0||e.text.rfind("buffer.",0)==0))fail("E_VERSION","operacion Bytes/Resource requiere OMC5");for(auto&a:e.args)noDev6Expr(a);};
            std::function<void(const std::vector<Stmt>&)> noDev6Block=[&](const std::vector<Stmt>&b){for(auto&st:b){noDev6(st.declared);noDev6Expr(st.expr);noDev6Block(st.body);noDev6Block(st.other);}};
            for(auto&d:p.records)for(auto&f:d.fields)noDev6(f.type);
            for(auto&f:p.functions){noDev6(f.result);for(auto&a:f.params)noDev6(a.type);noDev6Block(f.body);}
        }
        if(representationVersion<6) {
            std::function<void(const Type&)> noOption=[&](const Type&t){if(t.kind==Type::Option)fail("E_VERSION","Option requiere OMC6");for(auto&q:t.parts)noOption(q);};
            std::function<void(const Expr&)> noOptionExpr=[&](const Expr&e){if(e.kind==Expr::Some||e.kind==Expr::None)fail("E_VERSION","Some/None requieren OMC6");for(auto&a:e.args)noOptionExpr(a);};
            std::function<void(const std::vector<Stmt>&)> noOptionBlock=[&](const std::vector<Stmt>&b){for(auto&st:b){if(st.kind==Stmt::MatchOption)fail("E_VERSION","match Option requiere OMC6");noOption(st.declared);noOptionExpr(st.expr);noOptionBlock(st.body);noOptionBlock(st.other);}};
            for(auto&d:p.records)for(auto&f:d.fields)noOption(f.type);
            for(auto&f:p.functions){noOption(f.result);for(auto&a:f.params)noOption(a.type);noOptionBlock(f.body);}
        }
        if(representationVersion<7) {
            std::function<void(const Type&)> noWideInt=[&](const Type&t){if(isInteger(t)&&t.kind!=Type::U32)fail("E_VERSION","tipos enteros extendidos requieren OMC7");for(auto&q:t.parts)noWideInt(q);};
            std::function<void(const Expr&)> noWideExpr=[&](const Expr&e){if(e.kind==Expr::Number&&e.annotation.kind!=Type::Unknown&&e.annotation.kind!=Type::U32)fail("E_VERSION","literales enteros extendidos requieren OMC7");for(auto&a:e.args)noWideExpr(a);};
            std::function<void(const std::vector<Stmt>&)> noWideBlock=[&](const std::vector<Stmt>&b){for(auto&st:b){noWideInt(st.declared);noWideExpr(st.expr);noWideBlock(st.body);noWideBlock(st.other);}};
            for(auto&d:p.records)for(auto&f:d.fields)noWideInt(f.type);
            for(auto&f:p.functions){noWideInt(f.result);for(auto&a:f.params)noWideInt(a.type);noWideBlock(f.body);}
        }
        if(representationVersion<8) {
            if(!p.enums.empty())fail("E_VERSION","enum requiere OMC8");
            std::function<void(const Expr&)> noEnumExpr=[&](const Expr&e){if(e.kind==Expr::Variant)fail("E_VERSION","constructor enum requiere OMC8",e.loc);for(auto&a:e.args)noEnumExpr(a);};
            std::function<void(const std::vector<Stmt>&)> noEnumBlock=[&](const std::vector<Stmt>&b){for(auto&st:b){if(st.kind==Stmt::MatchEnum)fail("E_VERSION","match enum requiere OMC8",st.loc);noEnumExpr(st.expr);noEnumBlock(st.body);noEnumBlock(st.other);for(auto&arm:st.arms)noEnumBlock(arm);}};
            for(auto&f:p.functions)noEnumBlock(f.body);
        }
        if(representationVersion<9) {
            std::function<void(const Type&)> noProductType=[&](const Type&t){ if(t.kind==Type::Tuple||t.kind==Type::Array)fail("E_VERSION","Tuple/Array requieren OMC9"); for(auto&q:t.parts)noProductType(q); };
            std::function<void(const Expr&)> noProductExpr=[&](const Expr&e){ if(e.kind==Expr::Call&&(e.text=="tuple"||e.text.rfind("tuple.",0)==0||e.text=="array"||e.text.rfind("array.",0)==0))fail("E_VERSION","operacion Tuple/Array requiere OMC9"); for(auto&a:e.args)noProductExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noProductBlock=[&](const std::vector<Stmt>&b){ for(auto&st:b){ noProductType(st.declared); noProductExpr(st.expr); noProductBlock(st.body); noProductBlock(st.other); for(auto&arm:st.arms)noProductBlock(arm); } };
            for(auto&d:p.records)for(auto&f:d.fields)noProductType(f.type);
            for(auto&d:p.enums)for(auto&v:d.variants)if(v.hasPayload)noProductType(v.payload);
            for(auto&f:p.functions){ noProductType(f.result); for(auto&a:f.params)noProductType(a.type); noProductBlock(f.body); }
        }
        if(representationVersion<10) {
            std::function<void(const Type&)> noViewType=[&](const Type&t){ if(t.kind==Type::View)fail("E_VERSION","View requiere OMC10"); for(auto&q:t.parts)noViewType(q); };
            std::function<void(const Expr&)> noViewExpr=[&](const Expr&e){ if(e.kind==Expr::Call&&(e.text=="view"||e.text.rfind("view.",0)==0))fail("E_VERSION","operacion View requiere OMC10"); for(auto&a:e.args)noViewExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noViewBlock=[&](const std::vector<Stmt>&b){ for(auto&st:b){ noViewType(st.declared); noViewExpr(st.expr); noViewBlock(st.body); noViewBlock(st.other); for(auto&arm:st.arms)noViewBlock(arm); } };
            for(auto&d:p.records)for(auto&f:d.fields)noViewType(f.type);
            for(auto&d:p.enums)for(auto&variant:d.variants)if(variant.hasPayload)noViewType(variant.payload);
            for(auto&f:p.functions){ noViewType(f.result); for(auto&a:f.params)noViewType(a.type); noViewBlock(f.body); }
        }
        if(representationVersion<11) {
            std::function<void(const std::vector<Stmt>&)> noIter=[&](const std::vector<Stmt>&b){ for(auto&st:b){ if(st.kind==Stmt::ForEach)fail("E_VERSION","for-in requiere OMC11",st.loc); noIter(st.body); noIter(st.other); for(auto&arm:st.arms)noIter(arm); } };
            for(auto&f:p.functions)noIter(f.body);
        }
        if(representationVersion<12) {
            std::function<void(const Type&)> noAlpha8LoanType=[&](const Type&t){ if(t.kind==Type::BorrowMut)fail("E_VERSION","BorrowMut requiere OMC12"); for(const auto&q:t.parts)noAlpha8LoanType(q); };
            std::function<void(const Expr&)> noAlpha8LoanExpr=[&](const Expr&e){ if(e.kind==Expr::Call&&e.text=="borrow_mut")fail("E_VERSION","borrow_mut requiere OMC12",e.loc); for(const auto&a:e.args)noAlpha8LoanExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noAlpha8LoanBlock=[&](const std::vector<Stmt>&b){
                for(const auto&st:b){
                    noAlpha8LoanType(st.declared);
                    noAlpha8LoanExpr(st.expr);
                    if((st.kind==Stmt::Let||st.kind==Stmt::Var)&&st.expr.kind==Expr::Call&&(st.expr.text=="borrow"||st.expr.text=="borrow_mut"))
                        fail("E_VERSION","prestamos locales persistentes requieren OMC12",st.loc);
                    noAlpha8LoanBlock(st.body); noAlpha8LoanBlock(st.other); for(const auto&arm:st.arms)noAlpha8LoanBlock(arm);
                }
            };
            for(const auto&d:p.records)for(const auto&field:d.fields)noAlpha8LoanType(field.type);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noAlpha8LoanType(v.payload);
            for(const auto&fn:p.functions){ noAlpha8LoanType(fn.result); for(const auto&a:fn.params)noAlpha8LoanType(a.type); noAlpha8LoanBlock(fn.body); }
        }
        if(representationVersion<13){
            std::function<void(const Type&)> noFloatType=[&](const Type&t){ if(isFloat(t))fail("E_VERSION","f32/f64 requieren OMC13"); for(const auto&q:t.parts)noFloatType(q); };
            std::function<void(const Expr&)> noFloatExpr=[&](const Expr&e){ if(e.kind==Expr::Number&&isFloat(e.annotation))fail("E_VERSION","literal float requiere OMC13"); if(e.kind==Expr::Call&&(e.text=="f32"||e.text=="f64"))fail("E_VERSION","cast float requiere OMC13"); for(const auto&a:e.args)noFloatExpr(a); };
            std::function<void(const std::vector<Stmt>&)> noFloatBlock=[&](const std::vector<Stmt>&b){ for(const auto&st:b){ noFloatType(st.declared); noFloatExpr(st.expr); noFloatBlock(st.body); noFloatBlock(st.other); for(const auto&arm:st.arms)noFloatBlock(arm); } };
            for(const auto&d:p.records)for(const auto&field:d.fields)noFloatType(field.type);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noFloatType(v.payload);
            for(const auto&fn:p.functions){ noFloatType(fn.result); for(const auto&a:fn.params)noFloatType(a.type); noFloatBlock(fn.body); }
        }
        if(representationVersion<14){
            std::function<void(const Type&)> noUnicodeType=[&](const Type&t){ if(t.kind==Type::Char)fail("E_VERSION","Char requiere OMC14"); for(const auto&q:t.parts)noUnicodeType(q); };
            std::function<void(const Expr&)> noUnicodeExpr=[&](const Expr&e){
                if(e.kind==Expr::Call&&(e.text=="char.from_u32"||e.text=="char.codepoint"||e.text=="text.from_char"||e.text=="text.equals"||e.text=="text.byte_len"||e.text=="text.scalar_len"||e.text=="text.scalar_at"))
                    fail("E_VERSION","Unicode scalar/Text API requiere OMC14");
                for(const auto&a:e.args)noUnicodeExpr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noUnicodeBlock=[&](const std::vector<Stmt>&b){ for(const auto&st:b){ noUnicodeType(st.declared); noUnicodeExpr(st.expr); noUnicodeBlock(st.body); noUnicodeBlock(st.other); for(const auto&arm:st.arms)noUnicodeBlock(arm); } };
            for(const auto&d:p.records)for(const auto&field:d.fields)noUnicodeType(field.type);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noUnicodeType(v.payload);
            for(const auto&fn:p.functions){ noUnicodeType(fn.result); for(const auto&a:fn.params)noUnicodeType(a.type); noUnicodeBlock(fn.body); }
        }
        if(representationVersion<15){
            std::function<void(const Expr&)> noA813Expr=[&](const Expr&e){
                if(e.kind==Expr::Call&&e.text=="index")fail("E_VERSION","index syntax requiere OMC15");
                for(const auto&a:e.args)noA813Expr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noA813Block=[&](const std::vector<Stmt>&b){
                for(const auto&st:b){
                    if(st.kind==Stmt::Destructure||st.kind==Stmt::Break||st.kind==Stmt::Continue)
                        fail("E_VERSION","statement A81.3 requiere OMC15");
                    if((st.kind==Stmt::Match&&(st.name=="_"||st.otherName=="_"))||
                       (st.kind==Stmt::MatchOption&&st.name=="_")||
                       (st.kind==Stmt::MatchEnum&&std::find(st.armNames.begin(),st.armNames.end(),"_")!=st.armNames.end()))
                        fail("E_VERSION","wildcard pattern requiere OMC15");
                    noA813Expr(st.expr); noA813Block(st.body); noA813Block(st.other); for(const auto&arm:st.arms)noA813Block(arm);
                }
            };
            for(const auto&fn:p.functions)noA813Block(fn.body);
        }
        if(representationVersion<16){
            std::function<void(const Type&)> noRangeType=[&](const Type&t){
                if(t.kind==Type::Range)fail("E_VERSION","Range requiere OMC16");
                for(const auto&q:t.parts)noRangeType(q);
            };
            std::function<void(const Expr&)> noRangeExpr=[&](const Expr&e){
                if(e.kind==Expr::Call&&(e.text=="range.exclusive"||e.text=="range.inclusive"))
                    fail("E_VERSION","range syntax requiere OMC16");
                for(const auto&a:e.args)noRangeExpr(a);
            };
            std::function<void(const std::vector<Stmt>&)> noRangeBlock=[&](const std::vector<Stmt>&b){
                for(const auto&st:b){
                    noRangeType(st.declared); noRangeExpr(st.expr);
                    noRangeBlock(st.body); noRangeBlock(st.other); for(const auto&arm:st.arms)noRangeBlock(arm);
                }
            };
            for(const auto&d:p.records)for(const auto&field:d.fields)noRangeType(field.type);
            for(const auto&d:p.enums)for(const auto&v:d.variants)if(v.hasPayload)noRangeType(v.payload);
            for(const auto&fn:p.functions){ noRangeType(fn.result); for(const auto&a:fn.params)noRangeType(a.type); noRangeBlock(fn.body); }
        }
        if(representationVersion<19)for(const auto& f:p.functions)if(a85Block(f.body))
            fail("E_VERSION","task_scope/spawn/join requieren OMC19",f.loc);
        if(representationVersion<20)for(const auto& f:p.functions)if(a86Block(f.body))
            fail("E_VERSION","host.read/host.write/host.process/host.tcp/host.ffi requieren OMC20",f.loc);
        if(representationVersion<21)for(const auto& f:p.functions)if(a87Function(p,f))
            fail("E_VERSION","Borrow/BorrowMut devuelto, bit.*, Option<Resource>, primitivas de maquina (raw/port/cpu/atomic) y recursos nominales requieren OMC21",f.loc);
        if(representationVersion<21&&!p.threadLocals.empty())fail("E_VERSION","thread_local requiere OMC21",p.threadLocals.front().loc);
        if(representationVersion<21)for(const auto& f:p.functions)if(f.linkage())fail("E_VERSION","atributos de enlace (export/extern/section/noinline) requieren OMC21",f.loc);
        if(representationVersion<21)for(const auto& rd:p.records)if(rd.packed)fail("E_VERSION","packed struct requiere OMC21",rd.loc);
        if(representationVersion<21)for(const auto& rd:p.records)if(rd.opaque)fail("E_VERSION","opaque struct requiere OMC21",rd.loc);
        if(representationVersion<21)for(const auto& rd:p.records)if(rd.externC)fail("E_VERSION","extern struct requiere OMC21",rd.loc);
        if(representationVersion<21)for(const auto& rd:p.records)for(const auto& field:rd.fields)
            if(nominalResourceType(field.type))fail("E_VERSION","campo Resource nominal requiere OMC21",rd.loc);
        if(representationVersion<21)for(const auto& rd:p.records)for(const auto& field:rd.fields)
            if(typeContainsPending(p,field.type,rd.module))fail("E_VERSION","campo pending requiere OMC21",rd.loc);
        if(representationVersion<21)for(const auto& rd:p.records)for(const auto& field:rd.fields)
            if(ownedTupleType(p,field.type,rd.module))fail("E_VERSION","campo Tuple owning requiere OMC21",rd.loc);
        if(representationVersion<21)for(const auto& en:p.enums)for(const auto& v:en.variants)
            if(v.hasPayload&&(typeContainsResource(p,v.payload,en.module)||typeContainsPending(p,v.payload,en.module)))fail("E_VERSION","enum con payload Resource/pending requiere OMC21",en.loc);
        return p;
    }
    std::string readTextBounded(const std::filesystem::path&path,size_t maxBytes) {
        std::ifstream in(path,std::ios::binary|std::ios::ate);
        if(!in)fail("E_FILE","no se pudo abrir: "+path.string());
        auto n=in.tellg();
        if(n<0||static_cast<uint64_t>(n)>static_cast<uint64_t>(maxBytes))fail("E_LIMIT","archivo excede el limite de su formato");
        in.seekg(0);
        std::string s(static_cast<size_t>(n),'\0');
        if(n&&!in.read(&s[0],n))fail("E_FILE","lectura incompleta");
        return s;
    }
    // A whole file that is going to be held in memory: it must fit in what is left of the memory budget (the format of a file, not the size of the file, is what the callers of readTextBounded bound).
    std::string readText(const std::filesystem::path&path) {
        std::error_code ec;
        const auto size=std::filesystem::file_size(path,ec);
        if(!ec)budgetReserve(static_cast<uint64_t>(size),"el archivo de entrada");
        return readTextBounded(path,std::numeric_limits<size_t>::max());
    }
    std::string readUtf8TextBounded(const std::filesystem::path&path,size_t maxBytes) {
        auto s=readTextBounded(path,maxBytes);
        validateUTF8(s);
        return s;
    }
    std::string readUtf8Text(const std::filesystem::path&path) {
        auto s=readText(path);
        validateUTF8(s);
        return s;
    }
}

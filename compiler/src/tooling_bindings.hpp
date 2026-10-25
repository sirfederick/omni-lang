#pragma once
#include "omni.hpp"

namespace omni {
// The Particle lexer supplies these tokens; tooling does not parse or resolve
// source independently. Locations are the lexer's UTF-8 byte columns.
std::vector<std::pair<std::string,Loc>> sourceIdentifiers(const std::string&);

inline std::string bindingIndexJson(const Program& program) {
    using Token=std::pair<std::string,Loc>;
    std::map<std::string,std::vector<Token>> tokens;
    for(const auto& source:program.sources)
        if(source.extension()==".omni")tokens[source.string()]=sourceIdentifiers(readUtf8Text(source));
    struct Occurrence { std::string symbol,name,role; Loc loc; };
    std::vector<Occurrence> occurrences;
    bool complete=program.genericTemplates.empty()&&program.traits.empty()&&program.traitImpls.empty();
    auto add=[&](const std::string& symbol,const std::string& name,const Loc& loc,const std::string& role,bool forward) {
        if(symbol.empty()||name.empty()||loc.file.empty()||!loc.line){complete=false;return;}
        const auto found=tokens.find(loc.file);
        if(found==tokens.end()){complete=false;return;}
        // A declaration Loc may name `func`, `let`, or a receiver mode. Only
        // search forward on that same line. References must start exactly at Loc.
        for(const auto& token:found->second) {
            if(token.second.line!=loc.line||token.second.column<loc.column)continue;
            if(!forward&&token.second.column!=loc.column)break;
            if(token.first!=name){if(!forward)break;continue;}
            auto where=token.second;where.file=loc.file;
            occurrences.push_back({symbol,name,role,where});return;
        }
        complete=false;
    };
    std::map<std::string,const Function*> functions;
    for(const auto& fn:program.functions)if(!fn.generated)functions[fn.key]=&fn;
    for(const auto& fn:program.functions) {
        if(fn.generated){complete=false;continue;}
        const auto global="function:"+fn.key;
        add(global,fn.name,fn.loc,"declaration",true);
        auto local=[&](int id){return id<0?std::string():global+"/local:"+std::to_string(id);};
        for(const auto& param:fn.params)add(local(param.binding),param.name,param.loc,"declaration",true);
        std::function<void(const Expr&)> expr;
        std::function<void(const std::vector<Stmt>&)> block;
        expr=[&](const Expr& e) {
            if(e.kind==Expr::Ref&&e.binding>=0)add(local(e.binding),e.text,e.loc,"reference",false);
            if(e.kind==Expr::Call&&functions.count(e.resolved)) {
                const auto& callee=*functions.at(e.resolved);
                auto loc=e.loc;
                const auto dot=e.text.rfind('.');
                if(dot!=std::string::npos)loc.column+=dot+1;
                if(e.methodCall){complete=false;}
                else add("function:"+callee.key,callee.name,loc,"reference",false);
            }
            if(e.kind==Expr::ClosureCall||e.kind==Expr::Join||e.kind==Expr::Cancel||e.kind==Expr::Deadline||
               e.kind==Expr::Send||e.kind==Expr::Receive||e.kind==Expr::Close)complete=false;
            for(const auto& arg:e.args)expr(arg);
            if(e.closureBody)block(*e.closureBody);
        };
        block=[&](const std::vector<Stmt>& body) {
            for(const auto& s:body) {
                if(s.kind==Stmt::Let||s.kind==Stmt::Var||s.kind==Stmt::Spawn)
                    add(local(s.binding),s.name,s.loc,"declaration",true);
                if(s.kind==Stmt::Assign)add(local(s.binding),s.name,s.loc,"reference",false);
                if(s.kind==Stmt::Match||s.kind==Stmt::MatchOption||s.kind==Stmt::MatchEnum||s.kind==Stmt::Destructure||s.kind==Stmt::ForEach)
                    complete=false; // mappings for lowered/pattern binders must never be guessed
                expr(s.expr);block(s.body);block(s.other);
                for(const auto& arm:s.arms)block(arm);
            }
        };
        block(fn.body);
    }
    std::sort(occurrences.begin(),occurrences.end(),[](const auto& a,const auto& b){
        return std::tie(a.loc.file,a.loc.line,a.loc.column,a.symbol,a.role)<std::tie(b.loc.file,b.loc.line,b.loc.column,b.symbol,b.role);
    });
    occurrences.erase(std::unique(occurrences.begin(),occurrences.end(),[](const auto& a,const auto& b){
        return std::tie(a.loc.file,a.loc.line,a.loc.column,a.symbol,a.role)==std::tie(b.loc.file,b.loc.line,b.loc.column,b.symbol,b.role);
    }),occurrences.end());
    std::ostringstream out;
    out<<"{\"schema\":\"omni.bindings/1\",\"coordinate\":\"utf8-byte-1-based\",\"complete\":"<<(complete?"true":"false")<<",\"occurrences\":[";
    bool first=true;
    for(const auto& entry:occurrences) {
        if(!first)out<<',';
        first=false;
        out<<"{\"symbol\":"<<quote(entry.symbol)<<",\"name\":"<<quote(entry.name)<<",\"role\":"<<quote(entry.role)
           <<",\"source\":"<<quote(entry.loc.file)<<",\"line\":"<<entry.loc.line<<",\"column\":"<<entry.loc.column<<",\"length\":"<<entry.name.size()<<'}';
    }
    out<<"]}\n";return out.str();
}
}

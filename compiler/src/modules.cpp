#include "omni.hpp"
namespace omni  {
    namespace fs=std::filesystem;
    namespace  {
        void locations(Program&p,const std::string&file) {
            std::function<void(Expr&)>ex=[&](Expr&e) {
                e.loc.file=file;
                for(auto&a:e.args)ex(a);
            };
            std::function<void(std::vector<Stmt>&)>bl=[&](std::vector<Stmt>&b) {
                for(auto&s:b) {
                    s.loc.file=file;
                    ex(s.expr);
                    bl(s.body);
                    bl(s.other);
                    for(auto&arm:s.arms)bl(arm);
                }
            };
            auto markFunction=[&](Function& f){
                f.loc.file=file;
                for(auto&g:f.generics)g.loc.file=file;
                for(auto&a:f.params)a.loc.file=file;
                bl(f.body);
            };
            for(auto&f:p.functions) markFunction(f);
            for(auto&f:p.genericTemplates) markFunction(f);
            for(auto&f:p.staticAsserts) markFunction(f);
            for(auto&d:p.records) { d.loc.file=file; for(auto&f:d.fields)f.loc.file=file; }
            for(auto&d:p.enums) { d.loc.file=file; for(auto&v:d.variants)v.loc.file=file; }
            for(auto&d:p.threadLocals)d.loc.file=file;
            for(auto&m:p.modules)for(auto&i:m.imports)i.loc.file=file;
        }
        class Loader  {
            fs::path root;
            fs::path bundledStdlib;
            Program all;
            std::map<fs::path,std::string>seen;
            std::set<fs::path>active;
            std::set<std::string>moduleNames;
            bool inside(const fs::path&base,const fs::path&p) {
                auto a=base.begin(),b=p.begin();
                for(; a!=base.end(); ++a,++b)if(b==p.end()||*a!=*b)return false;
                return true;
            }
            // `base` is the source tree the importing file belongs to: the entry's directory, or the src/ of the dependency it was read from. A relative import may not leave it.
            std::string unit(const fs::path&path,int depth,const fs::path&base) {
                stackGuard("la cadena de imports");
                fs::path probe;
                for(auto& part:fs::absolute(path).lexically_normal()) {
                    probe/=part;
                    if(fs::is_symlink(fs::symlink_status(probe)))fail("E_IMPORT_PATH","enlaces simbolicos no admitidos en imports");
                }
                auto canon=fs::weakly_canonical(path);
                if(!inside(base,canon))fail("E_IMPORT_PATH","import fuera de la raiz del proyecto");
                if(active.count(canon))fail("E_IMPORT_CYCLE","ciclo de imports: "+canon.string());
                if(seen.count(canon))return seen.at(canon);
                auto s=readUtf8Text(canon);
                budgetCheck("el cargador de modulos");
                Program q;
                try {
                    q=parseParticle(s);
                }
                catch(Error&e) {
                    e.source=canon.string();
                    throw;
                }
                if(q.bundled||q.modules.size()!=1)fail("E_IMPORT","un archivo importado debe ser un modulo simple");
                locations(q,canon.string());
                auto name=q.module;
                if(!moduleNames.insert(name).second)fail("E_DUPLICATE","dos archivos declaran el mismo modulo: "+name);
                seen[canon]=name;
                active.insert(canon);
                all.sources.push_back(canon);
                for(auto&i:q.modules[0].imports) {
                    // `@dependency/relative.omni`: a module of a dependency declared in the manifest of this file's package, read where it is (never copied) after its lock is verified
                    if(!i.path.empty()&&i.path[0]=='@') {
                        const auto slash=i.path.find('/');
                        if(slash==std::string::npos||slash<2||slash+1>=i.path.size())fail("E_IMPORT_PATH","import de dependencia requiere @nombre/ruta.omni",i.loc);
                        const fs::path sub(i.path.substr(slash+1));
                        if(sub.is_absolute()||sub.has_root_name()||sub.extension()!=".omni")fail("E_IMPORT_PATH","ruta de dependencia debe ser relativa y .omni",i.loc);
                        for(const auto& part:sub)if(part==".."||part==".")fail("E_IMPORT_PATH","ruta de dependencia no puede contener . ni ..",i.loc);
                        const auto depSrc=lockedDependencySource(canon,i.path.substr(1,slash-1),bundledStdlib);
                        i.target=unit(depSrc/sub,depth+1,depSrc);
                        continue;
                    }
                    fs::path rel(i.path);
                    if(i.path.empty()||rel.is_absolute()||rel.has_root_name()||rel.extension()!=".omni")fail("E_IMPORT_PATH","import requiere ruta relativa .omni",i.loc);
                    i.target=unit(canon.parent_path()/rel,depth+1,base);
                }
                active.erase(canon);
                all.modules.push_back(std::move(q.modules[0]));
                for(auto&f:q.functions)all.functions.push_back(std::move(f));
                for(auto&f:q.genericTemplates)all.genericTemplates.push_back(std::move(f));
                for(auto&f:q.staticAsserts)all.staticAsserts.push_back(std::move(f));
                for(auto&d:q.genericRecordTemplates)all.genericRecordTemplates.push_back(std::move(d));
                for(auto&d:q.genericEnumTemplates)all.genericEnumTemplates.push_back(std::move(d));
                for(auto&d:q.traits)all.traits.push_back(std::move(d));
                for(auto&d:q.traitImpls)all.traitImpls.push_back(std::move(d));
                for(auto&d:q.records)all.records.push_back(std::move(d));
                for(auto&d:q.enums)all.enums.push_back(std::move(d));
                for(auto&d:q.threadLocals)all.threadLocals.push_back(std::move(d));
                return name;
            }
            public: explicit Loader(fs::path r,fs::path bundled):root(std::move(r)),bundledStdlib(std::move(bundled)) {
            }
            Program run(const fs::path&p) {
                all.module=unit(p,0,root);
                all.bundled=all.modules.size()>1;
                std::sort(all.modules.begin(),all.modules.end(),[](const ModuleInfo&a,const ModuleInfo&b) {
                    return a.name<b.name;
                });
                return std::move(all);
            }
        };
    }
    Program load(const fs::path&path,const fs::path&bundledStdlib) {
        auto canon=fs::weakly_canonical(fs::absolute(path));
        const auto ext=path.extension();
        // Sources and representations alike are bounded by the memory budget, not by a size inherited from an earlier version.
        auto s=ext==".owire"?readText(canon):readUtf8Text(canon);
        Program p;
        try {
            if(path.extension()==".owire")p=fromWire(std::vector<uint8_t>(s.begin(),s.end()));
            else if(path.extension()==".owave")p=parseWave(s);
            else if(path.extension()==".onme")p=parseONME(s);
            else  {
                p=parseParticle(s);
                if(!p.bundled&&!p.modules[0].imports.empty())p=Loader(canon.parent_path(),bundledStdlib).run(canon);
            }
            if(p.sources.empty()) {
                p.sources.push_back(canon);
                locations(p,canon.string());
            }
            // parseONME validates before checking its committed executable root.
            // Revalidating that checked IR would lower closures twice and change
            // the verified projection. Other parsers return unchecked IR.
            if(ext!=".onme")validate(p);
        }
        catch(Error&e) {
            if(e.source.empty())e.source=canon.string();
            throw;
        }
        return p;
    }
}

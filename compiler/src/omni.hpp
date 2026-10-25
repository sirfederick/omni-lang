#pragma once
#include <algorithm>
#include <atomic>
#include <bit>
#include <charconv>
#include <cmath>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstddef>
#include <deque>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>
namespace omni  {
inline constexpr const char* VERSION = "0.1.0.00";
    // ---- Limits and budgets (Adenda 015E) ----------------------------------------------------------------------------------------------------------------------------
    // The compiler has NO count or size limit inherited from earlier versions: how many modules, functions, types, fields, variants, parameters, tokens or bytes a program has is bounded by the resources of
    // the machine, MEASURED while the compiler works (the budget below), and by the width of the representations themselves (a tag is one byte). What remains here is of three kinds only:
    //  * the runtime contract of a value (Text and Bytes are at most 1 MiB; a host grant is at most 1 MiB; the output a run captures is at most 1 MiB): a property of the language, not of the compiler input;
    //  * a width of the representation (the tag of an enum is one byte, so an enum has at most 256 variants);
    //  * structural depths (nesting of types, blocks and expressions, aggregates in a layout): they protect the recursion of the checker and are provisional until they are derived from the stack budget.
    inline constexpr size_t OMNI_TEXT_VALUE_LIMIT_BYTES=1024*1024;
    inline constexpr size_t OMNI_ENVELOPE_MAX_BYTES=64*1024*1024;      // protocol bound of an OCAP cognitive envelope (an interface with an external provider), not a compiler input limit
    inline constexpr size_t OMNI_ENUM_MAX_VARIANTS=256;
    inline constexpr int OMNI_LIMIT_TYPE_DEPTH=8, OMNI_LIMIT_BLOCK_DEPTH=32, OMNI_LIMIT_EXPR_HEIGHT=64, OMNI_LIMIT_PAREN_DEPTH=192, OMNI_LIMIT_LAYOUT_DEPTH=16;
    struct Loc  {
        size_t line=0,column=0;
        std::string file;
        Loc(size_t l=0,size_t c=0,std::string f=""):line(l),column(c),file(std::move(f)) {
        }
    };
    // CP-16: an optional secondary location that explains a diagnostic (e.g. where the conflicting loan was created).
    struct RelatedLocation  {
        std::string role,note;
        Loc loc;
    };
    struct DiagnosticSemanticContext {
        std::string symbolId,symbol,owner,constraint,requiredCapability;
        int placeRoot=-1,loanBinding=-1,loanOrigin=-1;
        std::vector<int> projections;
        std::string loanKind;
        std::vector<std::string> fixClasses;
    };
    struct Error:std::runtime_error  {
        std::string code,output,source;
        std::string expected,replacement; // CP-16: optional proposal only; no check applies it
        size_t line,column;
        std::vector<RelatedLocation> related;
        std::optional<DiagnosticSemanticContext> semanticContext;
        Error(std::string c,std::string m,size_t l=0,size_t col=0): std::runtime_error(std::move(m)),code(std::move(c)),line(l),column(col) {
        }
    };
    [[noreturn]] inline void failRelated(const std::string& c,const std::string& m,Loc p,std::vector<RelatedLocation> related)  {
        Error e(c,m,p.line,p.column);
        e.source=p.file;
        for(auto& r:related)if(r.loc.line)e.related.push_back(std::move(r));
        throw e;
    }
    [[noreturn]] inline void fail(const std::string& c,const std::string& m,Loc p= {
    })  {
        Error e(c,m,p.line,p.column);
        e.source=p.file;
        throw e;
    }  // name preserves source spelling; key is recomputed by validation, never trusted from Wire.
    // ---- The resource budget of this process --------------------------------------------------------------------------------------------------------------------------
    // `live` is the heap the compiler holds right now, counted by the allocator of the driver (main.cpp counts every operator new/delete); `limit` is the budget derived from the host when the process starts (0 = not
    // enforced); `deadlineNs` is an optional work budget (OMNI_WORK_SECONDS); `stackBase/stackBytes` describe the stack of the compiler thread. The phases check the budget at their own checkpoints and answer
    // E_BUDGET with the figures, so a hostile or merely enormous input ends in a diagnostic, not in the kernel's OOM killer.
    struct ResourceAccount  {
        std::atomic<uint64_t> live{0},peak{0},limit{0},ticks{0};
        std::atomic<bool> counting{false};
        std::atomic<const char*> phase{"el arranque"};      // the last checkpoint passed: where the allocator was when it had to refuse
        std::atomic<uint64_t> sampleLive{0},sampleAvail{UINT64_MAX},lastAvail{0};     // automatic mode: the heap and the availability the host reported at the last sample
        std::atomic<bool> automatic{false};
        uint64_t (*hostAvailable)(uint64_t live)=nullptr;                              // what the host can still give while the compiler holds `live` bytes (set by the driver)
        std::atomic<int64_t> deadlineNs{0};
        uintptr_t stackBase=0;
        uint64_t stackBytes=0;
        std::string origin="not enforced";
    };
    inline ResourceAccount& resourceAccount()  {
        static ResourceAccount account;
        return account;
    }
    inline uint64_t residentBytes()  {
        uint64_t pages=0,resident=0;
        if(FILE* f=std::fopen("/proc/self/statm","r"))  {
            unsigned long long a=0,b=0;
            if(std::fscanf(f,"%llu %llu",&a,&b)==2)  {
                pages=a;
                resident=b;
            }
            std::fclose(f);
        }
        (void)pages;
        return resident*4096ull;
    }
    [[noreturn]] inline void budgetExceeded(const char* where,uint64_t used)  {
        auto& a=resourceAccount();
        fail("E_BUDGET",std::string("presupuesto de memoria agotado en ")+where+": el compilador retiene "+std::to_string(used>>20)+" MiB y el presupuesto es "+std::to_string(a.limit.load()>>20)
             +" MiB ("+a.origin+"); suba OMNI_MEMORY_MIB, libere memoria del host o divida el proyecto");
    }
    inline void budgetCheck(const char* where)  {
        auto& a=resourceAccount();
        a.phase.store(where,std::memory_order_relaxed);
        const auto limit=a.limit.load(std::memory_order_relaxed);
        // In a build that counts the heap the allocator refuses any allocation that would take it past the budget, so the heap never exceeds it and there is nothing to test here.
        // A build that does not count (sanitizers) samples the resident set instead.
        if(limit&&!a.counting.load(std::memory_order_relaxed)&&(a.ticks.fetch_add(1,std::memory_order_relaxed)&0xFFu)==0)  {
            const uint64_t used=residentBytes();
            if(used>limit)budgetExceeded(where,used);
        }
        const auto deadline=a.deadlineNs.load(std::memory_order_relaxed);
        if(deadline!=0&&std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count()>deadline)
            fail("E_BUDGET",std::string("presupuesto de trabajo agotado en ")+where+" (OMNI_WORK_SECONDS)");
    }
    // An input that is going to be held in memory must fit: in what is left of an explicit budget, or in what the host reports it can still give.
    inline void budgetReserve(uint64_t bytes,const char* what)  {
        auto& a=resourceAccount();
        const auto limit=a.limit.load(std::memory_order_relaxed);
        const uint64_t held=a.counting.load(std::memory_order_relaxed)?a.live.load(std::memory_order_relaxed):residentBytes();
        if(limit)  {
            if(held>limit||bytes>limit-held)fail("E_BUDGET",std::string("presupuesto de memoria agotado: ")+what+" ocupa "+std::to_string(bytes>>20)+" MiB y quedan "+std::to_string((held>limit?0:limit-held)>>20)
                                                  +" MiB de "+std::to_string(limit>>20)+" MiB ("+a.origin+"); suba OMNI_MEMORY_MIB o divida el proyecto");
            return;
        }
        if(a.automatic.load(std::memory_order_relaxed)&&a.hostAvailable)  {
            const uint64_t available=a.hostAvailable(held);
            if(bytes>available)fail("E_BUDGET",std::string("memoria agotada: ")+what+" ocupa "+std::to_string(bytes>>20)+" MiB y el entorno informa "+std::to_string(available>>20)+" MiB disponibles ("+a.origin
                                    +"); libere memoria del host, fije OMNI_MEMORY_MIB o divida el proyecto");
        }
    }
    // The stack of the compiler thread is a budget too: a recursion that has no structural depth (a chain of imports) stops before the guard page, with a diagnostic.
    inline void stackGuard(const char* where)  {
        auto& a=resourceAccount();
        if(a.stackBase==0||a.stackBytes==0)return;
        char probe=0;
        const auto here=reinterpret_cast<uintptr_t>(&probe);
        const uint64_t used=here<a.stackBase?static_cast<uint64_t>(a.stackBase-here):0;
        if(used>a.stackBytes-a.stackBytes/8)fail("E_BUDGET",std::string("presupuesto de pila agotado en ")+where+": "+std::to_string(used>>20)+" MiB de "+std::to_string(a.stackBytes>>20)+" MiB (OMNI_STACK_KIB)");
    }
    struct Type  {
        enum Kind:uint8_t  {
            U8, U16, U32, U64, I8, I16, I32, I64, F32, F64,
            Bool, Char, Unknown, Param, Record, Enum, Result, Text, Bytes, Resource, Borrow, BorrowMut, Future, Stream, Option, Tuple, Array, View, Range
        }
        kind=Unknown;
        std::string name,key;
        std::vector<Type> parts;
        uint32_t extent=0; // Array<T,N>; zero for non-array types.
        Type(Kind k=Unknown):kind(k) {
        }
        bool operator==(const Type& o)const  {
            if(kind!=o.kind)return false;
            if(kind==Param)return name==o.name;
            if(kind==Record||kind==Enum)return (key.empty()?name:key)==(o.key.empty()?o.name:o.key);
            if(kind==Resource||kind==Borrow||kind==BorrowMut)return name==o.name;
            if(kind==Result||kind==Future||kind==Stream||kind==Option||kind==Tuple||kind==View||kind==Range)return parts==o.parts;
            if(kind==Array)return extent==o.extent&&parts==o.parts;
            return true;
        }
        bool operator!=(const Type& o)const {
            return !(*this==o);
        }
    };
    // CP-02: Resource<Vec<u32>> keeps its type arguments in `parts` until monomorphization renames it to a concrete record; the arguments are part of its identity.
    inline std::string typeName(const Type& t);
    inline std::string canonicalTypeIdentity(const Type& t);
    inline std::string nominalArguments(const Type& t,std::string(*name)(const Type&)) {
        if(t.parts.empty())return {};
        std::string r="<"; for(size_t i=0;i<t.parts.size();++i){if(i)r+=",";r+=name(t.parts[i]);} return r+">";
    }
    inline std::string typeName(const Type& t)  {
        switch(t.kind) {
            case Type::U8:return "u8";
            case Type::U16:return "u16";
            case Type::U32:return "u32";
            case Type::U64:return "u64";
            case Type::I8:return "i8";
            case Type::I16:return "i16";
            case Type::I32:return "i32";
            case Type::I64:return "i64";
            case Type::F32:return "f32";
            case Type::F64:return "f64";
            case Type::Bool:return "bool";
            case Type::Char:return "Char";
            case Type::Unknown:return "infer";
            case Type::Param:return t.name;
            case Type::Record: {
                // CP-05: a generic struct use carries its type arguments in `parts` until monomorphization.
                if(t.parts.empty())return t.name;
                std::string r=t.name+"<"; for(size_t i=0;i<t.parts.size();++i){if(i)r+=",";r+=typeName(t.parts[i]);} return r+">";
            }
            case Type::Enum:return t.name;
            case Type::Result:return "Result<"+typeName(t.parts.at(0))+","+typeName(t.parts.at(1))+">";
            case Type::Text:return "Text";
            case Type::Bytes:return "Bytes";
            case Type::Resource:return "Resource<"+t.name+nominalArguments(t,typeName)+">";
            case Type::Borrow:return "Borrow<"+t.name+nominalArguments(t,typeName)+">";
            case Type::BorrowMut:return "BorrowMut<"+t.name+nominalArguments(t,typeName)+">";
            case Type::Future:return "Future<"+typeName(t.parts.at(0))+">";
            case Type::Stream:return "Stream<"+typeName(t.parts.at(0))+">";
            case Type::Option:return "Option<"+typeName(t.parts.at(0))+">";
            case Type::Tuple: { std::string r="Tuple<"; for(size_t i=0;i<t.parts.size();++i){if(i)r+=",";r+=typeName(t.parts[i]);} return r+">"; }
            case Type::Array:return "Array<"+typeName(t.parts.at(0))+","+std::to_string(t.extent)+">";
            case Type::View:return "View<"+typeName(t.parts.at(0))+">";
            case Type::Range:return "Range<"+typeName(t.parts.at(0))+">";
        }
        fail("E_TYPE","tipo no soportado");
    }
    // CP-01/CP-04 owned slots (spec/OWNED_SLOTS_CANDIDATE.md): the resource record travels in the call text (`slots.put<mod.Rec>`) so that Wave, Wire and ONME need
    // no new form. The key itself is the identity that keeps a buffer's cells to one resource type: the runtime compares the whole string, never a hash of it.
    inline std::string slotCallKey(const std::string& text) {
        const auto lt=text.find('<');
        return (lt==std::string::npos||text.back()!='>')?std::string():text.substr(lt+1,text.size()-lt-2);
    }
    inline std::string canonicalTypeIdentity(const Type& t) {
        switch(t.kind) {
            case Type::U8:return "u8";
            case Type::U16:return "u16";
            case Type::U32:return "u32";
            case Type::U64:return "u64";
            case Type::I8:return "i8";
            case Type::I16:return "i16";
            case Type::I32:return "i32";
            case Type::I64:return "i64";
            case Type::F32:return "f32";
            case Type::F64:return "f64";
            case Type::Bool:return "bool";
            case Type::Char:return "Char";
            case Type::Unknown:return "infer";
            case Type::Param:return "param:"+t.name;
            case Type::Record: {
                std::string r="record:"+(t.key.empty()?t.name:t.key);
                if(!t.parts.empty()){ r+="<"; for(size_t i=0;i<t.parts.size();++i){if(i)r+=",";r+=canonicalTypeIdentity(t.parts[i]);} r+=">"; }
                return r;
            }
            case Type::Enum:return "enum:"+(t.key.empty()?t.name:t.key);
            case Type::Result:return "Result<"+canonicalTypeIdentity(t.parts.at(0))+","+canonicalTypeIdentity(t.parts.at(1))+">";
            case Type::Text:return "Text";
            case Type::Bytes:return "Bytes";
            case Type::Resource:return "Resource<"+t.name+nominalArguments(t,canonicalTypeIdentity)+">";
            case Type::Borrow:return "Borrow<"+t.name+nominalArguments(t,canonicalTypeIdentity)+">";
            case Type::BorrowMut:return "BorrowMut<"+t.name+nominalArguments(t,canonicalTypeIdentity)+">";
            case Type::Future:return "Future<"+canonicalTypeIdentity(t.parts.at(0))+">";
            case Type::Stream:return "Stream<"+canonicalTypeIdentity(t.parts.at(0))+">";
            case Type::Option:return "Option<"+canonicalTypeIdentity(t.parts.at(0))+">";
            case Type::Tuple: {
                std::string r="Tuple<";
                for(size_t i=0;i<t.parts.size();++i){if(i)r+=",";r+=canonicalTypeIdentity(t.parts[i]);}
                return r+">";
            }
            case Type::Array:return "Array<"+canonicalTypeIdentity(t.parts.at(0))+","+std::to_string(t.extent)+">";
            case Type::View:return "View<"+canonicalTypeIdentity(t.parts.at(0))+">";
            case Type::Range:return "Range<"+canonicalTypeIdentity(t.parts.at(0))+">";
        }
        fail("E_TYPE","tipo no soportado");
    }
    inline bool hasUnresolvedNominalIdentity(const Type& t) {
        if((t.kind==Type::Record||t.kind==Type::Enum)&&t.key.empty())return true;
        for(const auto& part:t.parts)if(hasUnresolvedNominalIdentity(part))return true;
        return false;
    }
    Type parseType(const std::string&,Loc p= {
    });
    bool isInteger(const Type&);
    bool isSignedInteger(const Type&);
    unsigned integerWidth(const Type&);
    bool isFloat(const Type&);
    unsigned floatWidth(const Type&);
    uint64_t integerMaxUnsigned(const Type&);
    int64_t integerMinSigned(const Type&);
    int64_t integerMaxSigned(const Type&);
    std::string semanticTypeId(const Type&);
    std::string typeDescriptorJson(const Type&);
    std::string layoutDescriptorJson(const Type&);
    struct Param  {
        std::string name;
        Type type;
        int binding=-1;
        Loc loc;
        std::string receiverMode;
    };
    struct Stmt;
    struct Expr  {
        enum Kind:uint8_t  {
            Number,Boolean,Ref,Call,Unary,Binary,RecordInit,Field,Ok,Err,Text,Some,None,Variant,ClosureCall,Join,Cancel,Deadline,Channel,Send,Receive,Close,
            Try   // CP-05c: postfix `expr?`; lowered to a match before checking, never serialized
        }
        kind=Number;
        std::string text,resolved;
        uint64_t value=0;
        std::vector<Expr> args;
        uint32_t height=1; // Particle parser only: height of the tree rooted here (bounded at 64, the checker's structural limit); never serialized
        std::vector<Type> typeArgs; // explicit generic call arguments; Particle-only before monomorphization
        bool generatedReference=false; // set only by trait lowering; never parsed
        std::string genericTarget;  // concrete specialization key selected before semantic checking
        bool methodCall=false;   // Particle-only UFCS sugar: receiver::fn(args) -> fn(receiver,args)
        std::vector<std::string> names;
        std::vector<int> indices;
        Type type,annotation;
        int binding=-1;
        // Checker-only Place identity for resource operations. It is derived
        // from the AST, never serialized as authority-bearing metadata.
        int placeRoot=-1;
        std::vector<int> placePath;
        // A ClosureCall is syntactically immediate-only.  The checker records
        // its closed Copy environment and lowers execution to a generated
        // static function; the original form remains for Wave/Wire fidelity.
        std::vector<Param> closureParams;
        std::shared_ptr<std::vector<Stmt>> closureBody;
        std::vector<std::string> closureCaptures;
        std::vector<int> closureCaptureBindings;
        Loc loc;
    };
    struct Stmt  {
        enum IteratorProtocol:uint8_t { IteratorUnresolved, IteratorArray, IteratorView, IteratorRange };
        enum Kind:uint8_t  {
            Let,Var,Assign,Return,If,Loop,Print,PrintText,Match,MatchOption,MatchEnum,ForEach,Destructure,Break,Continue,TaskScope,Spawn
        }
        kind=Return;
        std::string name,text,otherName;
        std::vector<std::string> names;
        std::vector<int> bindings;
        Type declared;
        Expr expr;
        std::vector<Stmt> body,other;
        // General enum match arms (alpha.3). Parallel vectors preserve a compact IR without a recursive helper type.
        std::vector<std::string> armVariants,armNames;
        std::vector<std::vector<Stmt>> arms;
        std::vector<int> armBindings,armVariantIndices,armPayloadFields;
        int binding=-1,otherBinding=-1;
        IteratorProtocol iteratorProtocol=IteratorUnresolved;
        Loc loc;
    };
    struct GenericParam {
        std::string name;
        std::string constraint="Any";
        Loc loc;
    };
    struct Function  {
        std::string name,module,key;
        std::vector<GenericParam> generics;
        std::vector<Param> params;
        Type result=Type::U32;
        bool pub=false;
        std::set<std::string> capabilities;          // single source of truth for declared/requested effects
        bool effectful() const noexcept { return !capabilities.empty(); }
        std::set<std::string> directCapabilities;    // inferred from direct operations
        std::set<std::string> requiredCapabilities;  // direct + transitive
        std::set<std::string> excessCapabilities;    // declared - required
        std::set<std::string> calledFunctions;
        std::vector<Stmt> body;
        std::vector<Type> locals;
        bool isConst=false;   // CP-07 (spec/STATIC_DATA_CANDIDATE.md): `const NAME Type = literal` is a pure function without parameters; a use of NAME is a call. Never serialized: a checked program has only calls.
        // CP-07 / MN-07, MN-13, MN-16 (spec/LINKAGE_ABI_CANDIDATE.md): the link-time identity of a function, in the source and in every representation (Wave21/OMC21).
        std::string exportName;   // export "sym": the C symbol (SysV, integers only) that reaches this function
        std::string externName;   // extern "sym": the function is defined elsewhere (no body); calls reach the symbol; it needs ffi.call
        std::string section;      // section ".name": the code goes to that section
        bool noInline=false;      // noinline: the function stays a call
        bool isExtern=false;
        bool linkage() const noexcept { return !exportName.empty()||isExtern||!section.empty()||noInline; }
        bool isStaticAssert=false;   // CP-07 (spec/STATIC_ASSERT_CANDIDATE.md): `static_assert(cond, "why")` is a pure function () bool evaluated by the checker and then dropped; never serialized
        std::string assertMessage;
        bool generated=false;
        std::set<std::string> generatedTypeKeys; // validated substitutions; never deserialized
        bool closureGenerated=false;
        bool requiresOwnedTupleFence=false; // checker-derived representation requirement, never deserialized authority
        std::string genericOrigin;
        Loc loc;
    };
    struct FieldDef  {
        std::string name;
        Type type;
        Loc loc;
    };
    // CP-11 (spec/THREAD_LOCAL_CANDIDATE.md): `thread_local NAME Type = literal`. A per-thread variable of an integer type with a constant initial
    // value; the freestanding backend lays every declaration out in one per-thread block (header, then variables in program order) and emits the
    // initial image as a template. The value is stored as magnitude + sign so Wave/Wire/Particle round-trip it exactly.
    struct ThreadLocalDef  {
        std::string name,module;
        bool pub=false;
        Type type;
        uint64_t magnitude=0;
        bool negative=false;
        Loc loc;
    };
    struct RecordDef  {
        std::string name,module,key;
        bool pub=false;
        bool opaque=false;   // CP-07 (spec/ADDRESS_DOMAINS_CANDIDATE.md): `opaque struct` - its literal and its fields can only be written in the declaring module (E_OPAQUE); Wave21/OMC21 only
        bool externC=false;  // CP-09 (spec/LINKAGE_ABI_CANDIDATE.md): `extern struct` - the C layout is a contract: integers and extern/plain structs only, natural C alignment, reached through an explicit address; Wave21/OMC21 only
        bool packed=false;   // CP-07 (spec/NATIVE_LAYOUT_CANDIDATE.md): `packed struct` has alignment 1 and no padding; Wave21/OMC21 only
        std::vector<FieldDef> fields;
        std::vector<GenericParam> generics;   // CP-05: non-empty only on generic struct templates
        Loc loc;
    };

    struct VariantDef  {
        std::string name;
        bool hasPayload=false;
        Type payload;
        int payloadField=-1; // LLVM aggregate field; assigned by validation.
        Loc loc;
    };
    struct EnumDef  {
        std::string name,module,key;
        bool pub=false;
        std::vector<VariantDef> variants;
        std::vector<GenericParam> generics;   // CP-05: non-empty only on generic enum templates
        Loc loc;
    };
    struct TraitDef {
        std::string name,module,key;
        bool pub=false;
        std::vector<Function> methods;   // CP-05b: body-less signatures; `Self` is a Type::Param
        Loc loc;
    };
    struct TraitImpl {
        std::string trait;
        Type forType;
        std::string module;
        std::vector<Function> methods;   // CP-05b: full definitions, specialized into ordinary functions
        Loc loc;
    };
    struct Import  {
        std::string alias,path,target;
        Loc loc;
    };
    struct ModuleInfo  {
        std::string name;
        std::vector<Import> imports;
    };
    struct Program  {
        std::string module;
        std::string authoringSource; // normalized pre-lowering capsule; always rechecked
        std::vector<Function> functions;
        std::vector<Function> genericTemplates;
        std::vector<RecordDef> records;
        std::vector<RecordDef> genericRecordTemplates;   // CP-05: never encoded; only concrete specializations enter Wave/Wire
        std::vector<EnumDef> enums;
        std::vector<EnumDef> genericEnumTemplates;   // CP-05: never encoded; only concrete specializations enter Wave/Wire
        std::vector<TraitDef> traits;
        std::vector<TraitImpl> traitImpls;
        std::vector<ThreadLocalDef> threadLocals;   // CP-11: Wave21/OMC21 only
        std::vector<Function> staticAsserts;        // CP-07 (spec/STATIC_ASSERT_CANDIDATE.md): source-level, decided by validate(), kept only so the formatter can print them back; never serialized
        std::vector<ModuleInfo> modules;
        std::vector<std::filesystem::path> sources;
        // Particle source admits current semantics. Readers replace this with
        // the actual header version; writers derive the minimum from checked
        // features, rather than treating this input ceiling as a writer choice.
        uint32_t representationVersion=22;
        bool bundled=false;
    };
    Program parseParticle(const std::string&);
    Program parseParticleProgram(const std::string&);   // the authoring text of a whole program (a capsule): bounded by the representation limit, not by the size of one source file
    Program parseWave(const std::string&);
    std::vector<const ThreadLocalDef*> orderedThreadLocals(const Program&);   // module-major: the canonical order for layout and serialization
    struct ThreadLocalLayout { std::vector<uint64_t> offsets; uint64_t size=16; };   // offsets parallel to orderedThreadLocals; size includes the 16-byte header, multiple of 16
    ThreadLocalLayout threadLocalLayout(const Program&);
    // CP-07: layout of a plain record (integer fields and nested plain records) under the C rules of the target: fields in declaration order at natural
    // alignment (maxAlign caps it: 8 for x86-64, 4 for i386), tail padding to the record alignment; `packed` has alignment 1 and no padding.
    struct RecordLayout { std::vector<uint64_t> offsets; std::vector<std::pair<uint64_t,uint64_t>> padding; uint64_t size=0,align=1; };
    RecordLayout recordLayout(const Program&,const std::string& key,unsigned maxAlign);
    bool typeContainsResource(const Program&,const Type&,const std::string& module); // recursive classification only, never authority
    bool typeRequiresConsumption(const Program&,const Type&,const std::string& module); // pending sums; recursively derives resource/consumption obligations
    bool typeContainsPending(const Program&,const Type&,const std::string& module); // pending obligations anywhere in concrete product/sum metadata
    uint64_t recordIdentityWord(const Program&,const std::string& key,unsigned word);
    std::string plainRecordProblem(const Program&,const std::string& key);   // empty when the record is plain
    std::string particle(const Program&);
    enum class IdentityProjection { Current, Onme2Compatibility };
    std::string wave(const Program&,IdentityProjection=IdentityProjection::Current);
    std::vector<uint8_t> wire(const Program&);
    Type resolveOpenType(const Program&,const std::string& module,const std::set<std::string>& bound,Type);   // module-qualified identity of the nominal types a generic template's signature names
    uint32_t writerRepresentation(const Program&);   // the Wave/OMC version wave() and wire() emit for this program: the one authority for manifests and receipts
    Program fromWire(const std::vector<uint8_t>&);
    void validate(Program&);
    void requireMain(const Program&);
    struct HostPolicy;
    struct Value  {
        Type type;
        uint64_t bits=0;
        std::vector<Value> fields;
        std::string text;
        uint64_t handle=0;
        Value(Type t=Type::Unknown,uint64_t b=0):type(std::move(t)),bits(b) {
        }
        Value(Type t,std::string s):type(std::move(t)),text(std::move(s)) {
        }
    };
    struct EvalResult  {
        uint32_t result;
        std::string output;
        uint64_t steps;
    };
    Value evaluateValue(const Program&,const std::string& functionKey);   // a function without parameters; any result type (compile-time evaluation of constants)
    EvalResult evaluate(const Program&,const std::string& fn="main",const std::vector<Value>& args= {
    },const HostPolicy* hostPolicy=nullptr);
    std::string emitLLVM(const Program&);
    std::string emitLLVMHost(const Program&,const std::string& functionKey);
    // BAREMETAL-001 target profile (candidate): lowers a program for a freestanding target. No hosted
    // runtime symbol is referenced; checked arithmetic is generated inline and runtime services are
    // bound to Omni functions of `serviceModule` (provider) instead of external C symbols.
    // CP-07 / MN-01 (spec/TARGET_INTROSPECTION_CANDIDATE.md): what the program is being compiled FOR. `target.*` in the source is folded to a literal from these facts while the program is validated,
    // so the checked program (and everything derived from it) says what it was checked against. The CLI sets them from --target-profile / --target-isa before the program is loaded.
    struct TargetFacts {
        std::string arch="x86_64";      // x86_64 | i386
        uint32_t pointerWidth=64;
        bool littleEndian=true;
        bool hosted=true;                // false for a freestanding profile
        std::set<std::string> features={"sse2"};   // CPU features the generated code may assume
    };
    void setTargetFacts(const TargetFacts&);
    const TargetFacts& targetFacts();
    struct TargetProfile {
        std::string name;           // baremetal-x86_64 | baremetal-i386-boot
        std::string triple;
        std::string serviceModule;  // functions of this module are uninstrumented service code
        std::string entrySection;   // optional section of the exported entry symbol
        bool provider=false;        // bind omni_* services to serviceModule functions
        bool pvhNote=false;         // emit XEN_ELFNOTE_PHYS32_ENTRY (internal functions, relocation-free)
        uint64_t entryAddress=0;    // PVH note entry address (the linker script places the entry there)
        uint64_t entryStack=0;      // when nonzero the entry is a naked stub: esp = entryStack; jmp <program main>
        std::string threadEntry;      // module.function key (() -> u32): enables omni_switch_context / omni_thread_trampoline
        uint32_t isrCount=32;         // stubs for vectors 0..isrCount-1 (>= 32); vectors >= 32 push a zero error code
        uint32_t isrExtraVector=0;    // with exceptionHandler: one extra stub (vector 32..255) after the 32 architectural ones
        bool ring3Support=false;      // emit omni_enter_ring3 / omni_leave_ring3 (x86_64 profile)
        bool exceptionResume=false;   // with exceptionHandler: common tail saves caller-saved GPRs, resumes with iretq when the handler returns 0
        std::string isa="gpr";        // baremetal-x86_64 ISA mode: gpr (general registers only, floats rejected) | sse2 (floats, FP-state primitives)
        bool exceptionSaveFpu=false;  // with exceptionResume + sse2: the resumable tail also saves/restores x87/SSE state (fxsave64/fxrstor64)
        std::string exceptionHandler; // module.function key: terminal exception handler `(frame u64) u32`; enables the 32-stub ISR table
        uint64_t entryHandoffStore=0; // when nonzero the naked stub first stores %ebx (PVH start_info pointer) at this absolute address
    };
    std::string emitLLVMTarget(const Program&,const TargetProfile&);
    std::string quote(const std::string&);
    bool validIdentifier(const std::string&);
    bool validQualified(const std::string&);
    void validateUTF8(const std::string&);
    std::string readText(const std::filesystem::path&); // byte-preserving file read; historical name
    std::string readUtf8Text(const std::filesystem::path&);          // a whole file that must fit in what is left of the memory budget
    std::string readTextBounded(const std::filesystem::path&,size_t maxBytes);
    std::string readUtf8TextBounded(const std::filesystem::path&,size_t maxBytes);
    std::string sha256(const std::string&);
    std::string sha256File(const std::filesystem::path&);
    std::string programManifest(const Program&);
    std::string semanticFunctionId(const Function&,bool isTemplate=false);
    std::string compactOmniHash(const Program&);
    std::string buildKey(const Program&,const std::filesystem::path&,const std::string&,const std::string&,const std::string&,const std::string&);
    std::string artifactReceipt(const Program&,const std::filesystem::path&,const std::string&,const std::filesystem::path&,const std::string&,const std::string&,const std::string&,const std::string&,bool);
    std::string sourceMapJson(const Program&,const std::filesystem::path& artifact);
    Program load(const std::filesystem::path&,const std::filesystem::path& bundledStdlib={});
    std::filesystem::path bundledStandardLibrary(const std::filesystem::path& sdkRoot);
    std::string packageCommand(const std::string& action,const std::filesystem::path& root,
                               bool offline,const std::filesystem::path& bundledStdlib);
    struct HostPackageIdentity {
        std::string origin,name,version,manifestHash,sourceHash,lockHash;
    };
    HostPackageIdentity lockedHostPackage(const std::filesystem::path& root,
                                          const std::filesystem::path& bundledStdlib);
    // CP-05 (spec/PACKAGE_DEPENDENCY_IMPORTS_CANDIDATE.md): the src/ directory of the dependency `name` of the package that contains `importer`, once the lock of that package
    // has been verified (E_IMPORT_PATH: no package or not declared; E_PACKAGE_LOCK: no lock or drift).
    std::filesystem::path lockedDependencySource(const std::filesystem::path& importer,const std::string& name,const std::filesystem::path& bundledStdlib={});
    std::filesystem::path lockedHostSource(const std::filesystem::path& root,
                                           const std::string& modulePath,
                                           const std::filesystem::path& bundledStdlib);


    enum class MemoryDomain:uint8_t { Structural, Semantic, Operational, Confidential, Synaptic };
    enum class MemoryAuthority:uint8_t { CompilerAuthoritative, DeveloperDeclared, RuntimeObserved, VerifiedTool, VerifiedAgent, AIInferred, ExternalSource };
    struct MemoryNucleus {
        std::string id,kind,name,module,contentId,contractId,typeId,provenanceRef;
        std::set<std::string> domains,capabilities;
        std::map<std::string,std::string> authority;
        uint64_t epoch=0;
    };
    struct SynapticLink { std::string id,from,to,relation,authority; };
    struct SynapticBinding { std::string id,archetype,policy; std::vector<std::string> members; };
    struct NeuralEpoch {
        uint64_t sequence=0;
        std::string id,systemRoot,structuralRoot,semanticRoot,operationalRoot,confidentialRoot,synapticRoot;
    };
    struct SystemMemory { NeuralEpoch epoch; std::vector<MemoryNucleus> nuclei; std::vector<SynapticLink> links; std::vector<SynapticBinding> bindings; };
    struct RuntimeObservation { std::string id,functionNucleus,status,outputDigest; uint32_t result=0; uint64_t steps=0,sequence=0; };
    struct CognitiveProposal { std::string id,baseEpoch,agent,target,action,note,requiredCapability; };
    uint64_t advanceEpochSequence(uint64_t baseSequence);
    SystemMemory buildSystemMemory(const Program&,IdentityProjection=IdentityProjection::Current);
    SystemMemory buildObservedSystemMemory(const Program&,const EvalResult&,uint64_t sequence=1);
    std::string systemMemoryStore(const Program&);
    std::string systemMemoryStore(const SystemMemory&);
    SystemMemory parseSystemMemoryStore(const std::string&);
    std::string systemMemoryIndex(const std::string&);
    std::string systemMemorySummaryJson(const SystemMemory&);
    std::string querySystemMemoryJson(const SystemMemory&,const std::string&,const std::string&);
    std::string querySystemMemoryIndexedFileJson(const std::filesystem::path&,const std::string&,const std::string&,const std::string&);
    std::string traceSystemMemoryIndexedFileJson(const std::filesystem::path&,const std::string&,const std::string&,uint32_t depth=4);
    std::string impactSystemMemoryIndexedFileJson(const std::filesystem::path&,const std::string&,const std::string&);
    std::string traceSystemMemoryJson(const SystemMemory&,const std::string&,uint32_t depth=4);
    std::string impactSystemMemoryJson(const SystemMemory&,const std::string&);
    std::string memoryJson(const Program&);
    std::string graphJson(const Program&);
    std::string systemSummaryJson(const Program&);
    std::string neuralPulseJson(const Program&,const Program* previous=nullptr);
    std::string neuralPulseJson(const SystemMemory&,const SystemMemory* previous=nullptr);
    std::string runtimeObservationJson(const Program&,const EvalResult&,uint64_t,const SystemMemory* previous=nullptr);
    std::string cognitiveProjectionJson(const SystemMemory&,const std::string& selector="system");
    std::string cognitiveProjectionJson(const Program&,const std::string& selector="system");
    std::string synapticScaleBenchmarkJson(const Program&,const std::string&,uint64_t instances,uint64_t overrides);
    struct CognitiveBudget { uint64_t maxInputTokens=0,maxOutputTokens=0,maxCostMicrounits=0,maxLatencyMs=0; };
    struct CognitiveOffloadEnvelope {
        std::string id,baseEpoch,provider,selector,contextDigest,contextHex,requiredCapability;
        CognitiveBudget budget;
        uint64_t estimatedInputTokens=0,contextBytes=0,contextNuclei=0,sourceFilesScanned=0;
    };
    CognitiveOffloadEnvelope makeCognitiveOffloadEnvelope(const SystemMemory&,const std::string&,const std::string&,const CognitiveBudget&,const std::set<std::string>&);
    CognitiveOffloadEnvelope makeCognitiveOffloadEnvelope(const Program&,const std::string&,const std::string&,const CognitiveBudget&,const std::set<std::string>&);
    std::string serializeCognitiveOffloadEnvelope(const CognitiveOffloadEnvelope&);
    CognitiveOffloadEnvelope parseCognitiveOffloadEnvelope(const std::string&);
    std::string cognitiveOffloadSummaryJson(const CognitiveOffloadEnvelope&);
    std::string runCognitiveOffloadAdapterJson(const CognitiveOffloadEnvelope&);
    std::string querySystemJson(const Program&,const std::string&,const std::string&);
    std::string traceSystemJson(const Program&,const std::string&,uint32_t depth=4);
    std::string impactSystemJson(const Program&,const std::string&);
    CognitiveProposal makeCognitiveProposal(const SystemMemory&,const std::string&,const std::string&,const std::string&);
    std::string serializeCognitiveProposal(const CognitiveProposal&);
    CognitiveProposal parseCognitiveProposal(const std::string&);
    std::string cognitiveProposalSummaryJson(const CognitiveProposal&);
    SystemMemory applyCognitiveProposal(const SystemMemory&,const CognitiveProposal&,const std::set<std::string>&);
    SystemMemory applyCognitiveProposalBatch(const SystemMemory&,const std::vector<CognitiveProposal>&,const std::set<std::string>&);
    std::string onme(const Program&);
    Program parseONME(const std::string&);
    std::string onmeStatsJson(const Program&);

    struct CapabilitySpec {
        std::string name,category,scopeKind,riskClass,replacement;
        int introducedVersion=6;
        bool serializable=true,delegable=true,revocable=true,auditable=true,deprecated=false;
    };
    const std::map<std::string,CapabilitySpec>& capabilityRegistry();
    std::string canonicalCapability(const std::string&);
    bool isKnownCapability(const std::string&);
    std::set<std::string> legacyIoCapabilities();
    std::string capabilitiesJson(const Program&,bool explain);
    std::string capabilityRegistryJson();

    struct HostGrant {
        std::string capability,scope;
        uint64_t maxBytes=0;
    };
    struct HostPolicy {
        uint64_t generation=0,notAfterTick=0;
        std::vector<HostGrant> grants;
        bool allows(const std::string& capability,const std::string& subject,
                    uint64_t bytes,uint64_t tick,uint64_t expectedGeneration) const;
    };
    HostPolicy parseHostPolicy(const std::string&);
    std::string hostPolicySummaryJson(const HostPolicy&);
    struct HostProcessResult {
        uint32_t code=0;
        std::string payload;
    };
    HostProcessResult runHostProcess(const std::string& adapter,const std::string& payload,
                                     uint32_t maxBytes,uint32_t deadlineTicks);
    struct HostTcpResult {
        uint32_t code=0;
        std::string payload;
    };
    HostTcpResult runHostTcp(const std::string& endpoint,const std::string& payload,
                             uint32_t maxBytes,uint32_t deadlineTicks);
    struct HostFfiResult {
        uint32_t code=0;
        std::string payload;
    };
    HostFfiResult runHostFfi(const std::string& library,const std::string& payload,
                             uint32_t maxBytes);

    enum class FailureKind:uint16_t {
        CompileError=100, ValidationError=110, CapabilityDenied=210,
        DeadlineExceeded=420, Cancelled=430, ResourceExhausted=500, Trap=900
    };
    std::string failureName(FailureKind);

}

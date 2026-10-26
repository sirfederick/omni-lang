// SPDX-FileCopyrightText: 2026 Federico T. Begna
// SPDX-License-Identifier: MIT OR Apache-2.0
#include "host_sdk_schema.hpp"
#include "host_invocation_codec.hpp"
#include <functional>
#include <iostream>
#include <stdexcept>

using namespace omni;

static void require(bool condition,const char* message){
    if(!condition)throw std::runtime_error(message);
}

static Type nominal(Type::Kind kind,const std::string& key){
    Type value(kind);value.name=value.key=key;return value;
}

int main(){
    try{
        Program program;program.module="probe";
        Type scalar(Type::U32),request=nominal(Type::Record,"probe.Request");
        Type nested=nominal(Type::Record,"probe.Nested");
        Type specialized=nominal(Type::Record,"probe.Box__g_fixture");
        for(const auto& item:std::vector<std::pair<Type,Type>>{
                {request,scalar},{nested,request},{specialized,nested}}){
            RecordDef record;record.name=record.key=item.first.key;record.pub=true;
            record.fields.push_back({"value",item.second,{}});
            program.records.push_back(record);
        }
        Type choice=nominal(Type::Enum,"probe.Choice");
        EnumDef enumeration;enumeration.name=enumeration.key=choice.key;enumeration.pub=true;
        VariantDef empty;empty.name="Empty";
        VariantDef full;full.name="Full";full.hasPayload=true;full.payload=request;
        enumeration.variants={empty,full};program.enums.push_back(enumeration);
        Type tuple(Type::Tuple);tuple.parts={request,scalar};
        Type array(Type::Array);array.parts={request};array.extent=2;
        Type option(Type::Option);option.parts={request};
        Type result(Type::Result);result.parts={request,scalar};
        InvocationHash signature{};signature[0]=1;
        unsigned positive=0,negative=0;
        for(const auto& type:std::vector<Type>{scalar,request,nested,specialized,choice,tuple,array,option,result}){
            const auto schema=decodeHostSdkSchema(encodeHostSdkSchema(program,{type},type,signature));
            HostInvocationDescriptor descriptor;descriptor.signatureDigest=signature;
            descriptor.parameterTypeIds={invocationTypeId(type)};descriptor.returnTypeId=invocationTypeId(type);
            validateHostSdkSchema(schema,descriptor);
            const auto projected=hostSdkSchemaProgram(schema);
            const auto parameters=hostSdkSchemaRequestTypes(schema,projected);
            require(parameters.size()==1&&invocationTypeId(parameters[0])==invocationTypeId(type),"request identity changed");
            require(invocationTypeId(hostSdkSchemaResultType(schema,projected))==invocationTypeId(type),"result identity changed");
            if(type.kind==Type::Record){
                require(!projected.records.empty()&&projected.records.back().fields.size()==1,"record fields lost");
            }
            if(type.kind==Type::Enum){
                require(projected.enums.size()==1&&projected.enums[0].variants[1].hasPayload,"enum payload lost");
            }
            ++positive;
        }
        auto reject=[&](const std::function<void()>& operation){
            bool denied=false;
            try{operation();}catch(const Error& error){denied=error.code=="E_HOST_SDK_SCHEMA";}
            require(denied,"malformed schema or binding accepted");++negative;
        };
        const auto bytes=encodeHostSdkSchema(program,{request},request,signature);
        for(unsigned mutation=0;mutation<5;++mutation){
            auto broken=bytes;
            if(mutation==0)broken.pop_back();
            if(mutation==1)broken[0]^=1;
            if(mutation==2)broken[8]=2;
            if(mutation==3)for(unsigned i=44;i<48;++i)broken[i]=0;
            if(mutation==4)for(size_t i=broken.size()-4;i<broken.size();++i)broken[i]=0xff;
            reject([&](){(void)decodeHostSdkSchema(broken);});
        }
        const auto valid=decodeHostSdkSchema(bytes);
        auto broken=valid;broken.nodes[valid.requestRoots[0]].typeId[0]^=1;
        reject([&](){(void)hostSdkSchemaProgram(broken);});
        broken=valid;broken.nodes[valid.requestRoots[0]].nominalKey+="Forged";
        reject([&](){(void)hostSdkSchemaProgram(broken);});
        broken=valid;broken.nodes[valid.requestRoots[0]].children[0]=valid.requestRoots[0];
        reject([&](){(void)hostSdkSchemaProgram(broken);});
        HostInvocationDescriptor wrong;wrong.signatureDigest=signature;
        wrong.parameterTypeIds={invocationTypeId(request)};wrong.returnTypeId=invocationTypeId(request);
        wrong.signatureDigest[0]^=1;
        reject([&](){validateHostSdkSchema(valid,wrong);});
        std::cout<<"NOMINAL_PROJECTION positive="<<positive<<" negative="<<negative<<"\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}
}

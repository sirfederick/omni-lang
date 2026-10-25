#include "omni.hpp"
#include <array>
#include <memory>
#include <openssl/evp.h>
namespace omni {
namespace {
struct MdCtxDeleter {
    void operator()(EVP_MD_CTX* p) const noexcept { EVP_MD_CTX_free(p); }
};
class Sha256Provider {
    std::unique_ptr<EVP_MD_CTX,MdCtxDeleter> ctx;
public:
    Sha256Provider():ctx(EVP_MD_CTX_new()) {
        if(!ctx || EVP_DigestInit_ex(ctx.get(),EVP_sha256(),nullptr)!=1)
            fail("E_TOOL","OpenSSL EVP SHA-256 provider unavailable");
    }
    void update(const void* data,size_t n) {
        if(n && EVP_DigestUpdate(ctx.get(),data,n)!=1)
            fail("E_TOOL","OpenSSL EVP SHA-256 update failed");
    }
    std::string finish() {
        std::array<unsigned char,EVP_MAX_MD_SIZE> digest{};
        unsigned int n=0;
        if(EVP_DigestFinal_ex(ctx.get(),digest.data(),&n)!=1 || n!=32)
            fail("E_TOOL","OpenSSL EVP SHA-256 finalization failed");
        std::ostringstream o; o<<std::hex<<std::setfill('0');
        for(unsigned int i=0;i<n;++i)o<<std::setw(2)<<static_cast<unsigned>(digest[i]);
        return o.str();
    }
};
}
std::string sha256(const std::string& input){
    Sha256Provider h; h.update(input.data(),input.size()); return h.finish();
}
std::string sha256File(const std::filesystem::path& p){
    std::ifstream f(p,std::ios::binary); if(!f)fail("E_FILE","no se pudo leer para hash: "+p.string());
    Sha256Provider h; std::array<char,64*1024> buf{};
    for(;;){
        f.read(buf.data(),static_cast<std::streamsize>(buf.size()));
        const auto n=f.gcount(); if(n>0)h.update(buf.data(),static_cast<size_t>(n));
        if(f.eof())break;
        if(!f)fail("E_FILE","lectura incompleta para hash: "+p.string());
    }
    return h.finish();
}
}

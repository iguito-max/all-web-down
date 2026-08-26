# All Web Down

Uma interface minimalista para identificar formatos disponíveis em links públicos de mídia e iniciar o download sem sair da página.

## Como funciona

- O navegador envia o link para `/api/analyze`.
- Uma função Python usa `yt-dlp` para identificar a origem e listar formatos reais.
- O usuário escolhe qualidade ou formato.
- `/api/download` prepara o arquivo e o envia para um bucket privado temporário no Supabase.
- O navegador recebe uma URL assinada com `Content-Disposition: attachment` e inicia o download sem sair da página.

O projeto não mantém histórico e não aceita conteúdo privado ou protegido por DRM. O plano gratuito do Supabase limita cada arquivo temporário a 50 MB. Baixe apenas conteúdo que você tem autorização para salvar.

## Desenvolvimento

```bash
npm run check
vercel dev
```

## Deploy

O app usa um único entrypoint FastAPI no Vercel. A Edge Function do Supabase valida a identidade OIDC assinada do projeto Vercel, sem chave estática no código ou no navegador.

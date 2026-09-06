# togglemaster-cicd-templates

Catálogo central de *Templates Reutilizáveis* (Reusable Workflows) de GitHub Actions.

## 🎯 Propósito
Padronizar a esteira de CI/CD em um único lugar, garantindo conformidade, inspeção de qualidade (SonarCloud/Trivy) e empacotamento. Outros repositórios consomem estes fluxos, eliminando redundâncias.

## 🚀 Como Utilizar
Os repositórios chamam estes templates através da diretiva `uses:` em seus workflows locais.

### Módulos Disponíveis
- `validate.yml`: Realiza checkout, setup de Python e lint/testes unitários básicos.
- `security.yml`: Integrações com SonarQube para análise estática e *Code Smells*.
- `image.yml`: Constrói a imagem Docker (utilizando cache LHA) e empurra para o Amazon ECR de forma segura via autenticação nativa (OIDC `id-token: write`).
- `update-gitops.yml`: Realiza a promoção (*Delivery*) através de um robô, extraindo o SHA da imagem compilada e abrindo automaticamente um Pull Request formatado no `togglemaster-gitops`.

### Exemplo Simples (Consumo de Template)
```yaml
jobs:
  meu-job-security:
    uses: jhouzera/togglemaster-cicd-templates/.github/workflows/security.yml@main
    with:
      service-name: meu-servico
```

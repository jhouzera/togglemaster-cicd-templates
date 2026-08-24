# togglemaster-cicd-templates

Catálogo central de templates GitHub Actions da plataforma ToggleMaster.

## Objetivo

Este repositório centraliza a implementação das etapas comuns de CI/CD dos serviços. Os
repositórios de aplicação mantêm somente workflows adaptadores, responsáveis por definir
eventos, parâmetros, dependências, concorrência e o ambiente de destino.

O catálogo não contém código de microsserviços, Dockerfiles, manifests Kubernetes ou
infraestrutura Terraform.

## Templates disponíveis

Cada estágio da pipeline possui seu próprio workflow reutilizável:

- `validate.yml`: build, teste e lint por linguagem (`go` ou `python`).
- `security.yml`: scan de dependências/arquivos com Trivy, SAST com gosec ou bandit e
	SonarCloud opcional.
- `image.yml`: build, scan da imagem e push no Amazon ECR quando `push-images=true`.
- `update-gitops.yml`: altera uma tag em um arquivo de values e faz commit no repositório
	GitOps.
- `auto-pr.yml`: cria um Pull Request para branches `feat/**` e `bug/**`.

O arquivo `auto-pr-caller.yml` é um exemplo de caller local. Ele existe para mostrar como
conceder as permissões exigidas pelo reusable workflow.

O caller local usa `./.github/workflows/auto-pr.yml` porque os dois arquivos são publicados
no mesmo repositório. Essa referência só pode resolver o arquivo que existe no commit que
disparou o workflow; uma execução antiga não passa a usar correções publicadas depois.

Os templates possuem cache de dependências e autenticação AWS via OIDC. O repositório consumidor define a concorrência e o encadeamento entre estágios.

## Fluxo recomendado

```text
Pull Request
	-> validate
	-> security
	-> image (sem push, valida o build)

merge/tag de release
	-> image (OIDC + push no ECR)
	-> ArgoCD Image Updater ou update-gitops
	-> sincronização no cluster
```

Use apenas uma estratégia de promoção de imagem. A recomendada é o ArgoCD Image Updater,
com digest/tag imutável. Não encadeie `update-gitops.yml` junto com o Image Updater para o
mesmo serviço, pois os dois mecanismos podem competir pela fonte de verdade.

## Consumo remoto

Cada repositório de aplicação mantém apenas workflows adaptadores para definir eventos, concorrência, parâmetros e dependências entre os estágios:

```yaml
jobs:
	validate:
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/validate.yml@main
		with:
			service-name: auth-service
			service-language: go
			service-path: app/auth-service

	security:
		needs: validate
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/security.yml@main
		with:
			service-name: auth-service
			service-language: go
			service-path: app/auth-service
		secrets: inherit

	image:
		needs: security
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/image.yml@main
		with:
			service-name: auth-service
			service-path: app/auth-service
			service-dockerfile: app/auth-service/Dockerfile
			aws-region: us-east-1
			role-to-assume: ${{ vars.AWS_ROLE_TO_ASSUME }}
			ecr-repository-prefix: togglemaster-dev
			image-tag: ${{ github.ref_name }}
			push-images: ${{ github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v') }}
```

Para produção, prefira uma tag major estável (`@v1`) ou SHA de release em vez de `@main`.
O SHA torna a execução reproduzível e impede que uma alteração futura no catálogo mude um
pipeline sem revisão no repositório consumidor.

## Auto-PR

O reusable workflow aceita um único input:

| Input | Tipo | Obrigatório | Padrão | Descrição |
| --- | --- | --- | --- | --- |
| `target-branch` | string | não | `develop` | Branch base do Pull Request |

Caller remoto:

```yaml
name: auto-pr

on:
	push:
		branches:
			- 'feat/**'
			- 'bug/**'

permissions:
	contents: read
	pull-requests: write

jobs:
	auto-pr:
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/auto-pr.yml@v1
		with:
			target-branch: develop
```

O bloco `permissions` é obrigatório no caller. Permissões declaradas no reusable workflow
não elevam permissões que o caller não concedeu; sem `pull-requests: write`, o GitHub falha
com erro semelhante a:

```text
The workflow is requesting 'pull-requests: write', but is only allowed 'pull-requests: none'
```

O workflow usa `GITHUB_TOKEN` para consultar PRs existentes e criar um novo PR. Não é
necessário criar um PAT para esse caso. O repositório deve permitir que GitHub Actions crie
e aprove alterações conforme a política da organização.

## Inputs dos templates

### `validate.yml`

Obrigatórios: `service-name`, `service-language` (`go` ou `python`) e `service-path`.
Para Go, espera um `go.mod` e executa build, testes, vet e golangci-lint. Para Python,
espera `requirements.txt` e executa compileall e Ruff.

### `security.yml`

Obrigatórios: `service-name`, `service-language` e `service-path`. Aceita o secret opcional
`SONAR_TOKEN`. Trivy bloqueia vulnerabilidades `CRITICAL` detectadas, ignorando as não
corrigidas; SonarCloud é informativo porque o step está com `continue-on-error`.

### `image.yml`

Obrigatórios: `service-name`, `service-path`, `service-dockerfile`, `aws-region`,
`role-to-assume` e `image-tag`. `ecr-repository-prefix` tem padrão `togglemaster-dev`.
Quando `push-images=true`, a tag precisa seguir `vMAJOR.MINOR.PATCH` ou
`MAJOR.MINOR.PATCH`, o job exige OIDC e publica no ECR. Em PR, use `push-images=false` para
validar apenas o build e o scan.

### `update-gitops.yml`

Obrigatórios: `service-name`, `gitops-values-file` e `image-tag`, além dos secrets
`GITOPS_TOKEN` e `GITOPS_REPO`. `GITOPS_BRANCH` é opcional e usa `main` quando vazio.
O arquivo deve possuir a estrutura `services.<service-name>.image.tag`. A atualização usa
PyYAML e faz commit somente quando existe diferença.

## Secrets e permissões do consumidor

- `GITOPS_TOKEN`: token com escrita no repositório GitOps, somente se `update-gitops.yml`
	for usado.
- `GITOPS_REPO`: proprietário e nome do repositório GitOps.
- `GITOPS_BRANCH`: branch GitOps; usa `main` quando vazio.
- `SONAR_TOKEN`: opcional; habilita o scan SonarCloud.

Para `image.yml`, configure no caller `permissions: id-token: write` no job que chama o
reusable workflow. A role AWS deve confiar no repositório, branch/environment e audience
`sts.amazonaws.com` esperados pelo GitHub OIDC. Não use access keys estáticas.

Os templates não recebem secrets de runtime da aplicação. Banco, API keys e master keys
devem continuar no Secrets Manager, preferencialmente sincronizados por External Secrets.

O workflow de imagem publica somente tags semanticas `vMAJOR.MINOR.PATCH`. A promocao no
cluster e feita pelo ArgoCD Image Updater; o workflow legado `update-gitops.yml` nao deve
ser encadeado junto, pois ele grava SHA no values file e compete com o Image Updater.

## Segurança e governança

- Use `permissions` explícitas em todo caller; mantenha `contents: read` como padrão.
- Conceda `pull-requests: write` somente ao caller do auto-PR.
- Conceda `id-token: write` somente ao job que publica no ECR.
- Proteja `main`, `develop`, `qa` e `prod` conforme o processo de promoção.
- Exija revisão para mudanças em workflows e em este repositório de templates.
- Não coloque tokens, credenciais, state ou arquivos de plano em commits.
- Prefira SHAs ou tags imutáveis para ações externas e para este catálogo.
- Revise regularmente as versões de actions, Trivy, Go, Python e ferramentas de lint.

## Versionamento e publicação

Os consumidores usam `@main` enquanto o catálogo é inicializado. Após publicar a primeira versão, crie e mantenha a tag major `v1`; os consumidores devem então referenciar `@v1` ou, para máxima rastreabilidade, o SHA de um release.

Ao publicar uma alteração incompatível, crie uma nova major (`v2`). Alterações compatíveis
podem receber uma nova tag minor/patch e atualizar o ponteiro major após revisão.

## Configuração no GitHub

Se este repositório for privado, em **Settings > Actions > General > Access** habilite o acesso para os repositórios privados do proprietário. Sem essa permissão, os callers não conseguem resolver o workflow reutilizável, mesmo que o caminho e a referência estejam corretos.

Verifique também:

1. O reusable workflow está na branch/tag/SHA referenciada.
2. O arquivo está em `.github/workflows/` e possui `on: workflow_call`.
3. O caller concede todas as permissões necessárias.
4. O environment e a trust policy OIDC correspondem ao contexto do job.

## Troubleshooting

### `pull-requests: write` permitido como `none`

Adicione no workflow chamador:

```yaml
permissions:
	contents: read
	pull-requests: write
```

Permissões do caller e do reusable workflow são combinadas por restrição: o reusable não
pode ampliar o que o caller não autorizou.

Depois de adicionar a permissão, faça commit e push do caller. Se o erro vier de uma execução
antiga, reexecute o workflow a partir de um commit novo na branch. Em especial, não use como
referência de diagnóstico uma execução disparada antes da publicação da correção: ela ainda
será avaliada com o YAML antigo.

### Reusable workflow não encontrado

Confirme o owner, repositório, caminho e referência. Para repositórios privados, habilite o
acesso em **Settings > Actions > General > Access**. Valide também que o commit referenciado
contém o arquivo e que o workflow possui `on: workflow_call`.

### Falha ao assumir role AWS

Confirme `id-token: write`, `role-to-assume`, `aws-region`, a trust policy da role e o
`sub` emitido pelo GitHub. Em jobs que chamam reusable workflows, valide se o `environment:`
está no nível suportado pelo caller e não dependa de um claim que o GitHub não emite nesse
contexto.

### Push no ECR ou GitOps não ocorre

Confirme `push-images=true`, tag semântica, permissões da role ECR e secrets do GitOps.
Verifique se o arquivo de values existe e se a estrutura `services.<service>.image.tag`
está presente.

## Validação local

Com `actionlint` instalado, execute na raiz deste repositório:

```bash
for workflow in .github/workflows/*.yml; do
	actionlint - < "$workflow"
done
```

O uso de stdin é útil em ambientes onde o empacotamento do `actionlint` não consegue ler
caminhos do workspace diretamente.
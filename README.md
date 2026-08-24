# togglemaster-cicd-templates

Catálogo central de templates GitHub Actions da plataforma ToggleMaster.

## Templates disponíveis

Cada estágio da pipeline possui seu próprio workflow reutilizável:

- `validate.yml`: build, teste e lint por linguagem.
- `security.yml`: SCA com Trivy, SAST com gosec ou bandit e SonarCloud opcional.
- `image.yml`: build, scan da imagem e push no Amazon ECR somente na `main`.
- `update-gitops.yml`: atualização da tag da imagem no repositório GitOps após o push bem-sucedido.

Os templates possuem cache de dependências e autenticação AWS via OIDC. O repositório consumidor define a concorrência e o encadeamento entre estágios.

## Consumo

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

## Secrets exigidos pelo consumidor

- `GITOPS_TOKEN`: token com escrita no repositório GitOps.
- `GITOPS_REPO`: proprietário e nome do repositório GitOps.
- `GITOPS_BRANCH`: branch GitOps; usa `main` quando vazio.
- `SONAR_TOKEN`: opcional; habilita o scan SonarCloud.

O workflow de imagem publica somente tags semanticas `vMAJOR.MINOR.PATCH`. A promocao no
cluster e feita pelo ArgoCD Image Updater; o workflow legado `update-gitops.yml` nao deve
ser encadeado junto, pois ele grava SHA no values file e compete com o Image Updater.

## Versionamento

Os consumidores usam `@main` enquanto o catálogo é inicializado. Após publicar a primeira versão, crie e mantenha a tag major `v1`; os consumidores devem então referenciar `@v1` ou, para máxima rastreabilidade, o SHA de um release.

## Configuração no GitHub

Se este repositório for privado, em **Settings > Actions > General > Access** habilite o acesso para os repositórios privados do proprietário. Sem essa permissão, os callers não conseguem resolver o workflow reutilizável, mesmo que o caminho e a referência estejam corretos.
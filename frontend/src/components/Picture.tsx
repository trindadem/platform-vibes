export interface PictureProps {
  /** Endereço da imagem (ex.: link assinado devolvido pelo serviço). */
  src: string;
  /** Descrição para leitores de tela (obrigatória). */
  alt: string;
  /** Lado do quadrado em que a imagem cabe, em pixels, sem cortar. Padrão: 64. */
  size?: number;
}

/**
 * Imagem quadrada que se ajusta ao espaço sem distorcer (logo, foto de perfil, miniatura).
 *
 * @category Dados
 * @example
 * <Picture src="https://exemplo.com/logo.png" alt="Logo da empresa" size={48} />
 */
export function Picture({ src, alt, size = 64 }: PictureProps) {
  return <img src={src} alt={alt} width={size} height={size} className="rounded-md object-contain" />;
}

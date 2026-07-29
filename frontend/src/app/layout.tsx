import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { AppProviders } from '@/components/providers/AppProviders';
import { LayoutShell } from '@/components/layout/LayoutShell';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = { title: 'Sentinel-IQ', description: 'Cloud governance operations console' };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): JSX.Element {
  return <html lang="en" className="dark"><body className={inter.className}><AppProviders><LayoutShell>{children}</LayoutShell></AppProviders></body></html>;
}

import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "TPW Supplier Health",
  description: "The Perfect Wedding — Supplier Lifecycle Dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-50 min-h-screen`}>
        <nav className="bg-white border-b border-gray-200">
          <div className="w-full px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between h-14">
              <div className="flex items-center gap-6">
                <a
                  href="/"
                  className="text-lg font-bold text-gray-900 tracking-tight"
                >
                  TPW Supplier Health
                </a>
                <div className="hidden sm:flex items-center gap-4">
                  <a
                    href="/"
                    className="text-sm font-medium text-gray-600 hover:text-gray-900"
                  >
                    Overview
                  </a>
                  <a
                    href="/actions"
                    className="text-sm font-medium text-gray-600 hover:text-gray-900"
                  >
                    Action Queue
                  </a>
                </div>
              </div>
            </div>
          </div>
        </nav>
        <main className="w-full px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}

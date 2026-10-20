/***************************************************************************
               menu.h -- Interface file for Dynamic Menu Management                                   
                             -------------------                                         
    created              : Fri Aug 13 22:24:24 CEST 1999
    copyright            : (C) 1999 by Eric Espie                         
    email                : torcs@free.fr   
    version              : $Id$                                  
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 
 
#ifndef __MENU__H__
#define __MENU__H__

#include <string>


struct tMnuCallbackInfo
{
	void	*screen;
	int		labelId;
	int		buttonId;
	std::string	tip;
	std::string	disabledTip;
};



#endif /* __MENU__H__ */ 



